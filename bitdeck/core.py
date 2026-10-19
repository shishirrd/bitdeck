"""Image operations. Imported only by a short-lived worker, never by the UI."""
from __future__ import annotations

import io
import hashlib
import math
import os
from pathlib import Path
import tempfile
import warnings

MAX_INPUT = 64 * 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 16_384
FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class JobError(ValueError):
    pass


def bounded_int(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise JobError(f"{label} must be between {low} and {high}.")
    return value


def read_image(source):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    # Read from one open handle, with an actual byte cap, not a stat-only check.
    path = Path(source)
    if not path.is_file():
        raise JobError("Choose an existing image file.")
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size > MAX_INPUT:
            raise JobError("Input exceeds the 64 MiB limit.")
        raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise JobError("Input exceeds the 64 MiB limit.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        # Limit decoder selection to the three supported formats, regardless of suffix.
        with Image.open(io.BytesIO(raw), formats=list(FORMATS)) as image:
            if image.width * image.height > MAX_PIXELS or max(image.size) > MAX_SIDE:
                raise JobError("Image exceeds the 40 MP / 16,384 px limit.")
            if getattr(image, "n_frames", 1) != 1:
                raise JobError("Animated images are not supported in this release.")
            image.load()
            size = image.size
            original_format = image.format
            oriented = ImageOps.exif_transpose(image)
            # Rebuild from pixels: no EXIF, XMP, comments, profiles, or text chunks.
            mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
            clean = Image.new(mode, oriented.size)
            clean.paste(oriented.convert(mode))
    return clean, original_format, len(raw), size, hashlib.sha256(raw).hexdigest()


class BoundedWriter:
    """File facade that rejects encoders exceeding the output byte budget."""
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        if self.stream.tell() + len(data) > MAX_OUTPUT:
            raise JobError("Encoded output exceeds the 64 MiB limit.")
        return self.stream.write(data)

    def fileno(self):
        # Force encoders through write(); exposing a descriptor lets native
        # Pillow encoders bypass the output byte budget with direct fd writes.
        raise io.UnsupportedOperation("Direct descriptor writes are disabled")

    def __getattr__(self, key):
        return getattr(self.stream, key)


def publish_no_replace(temporary, output):
    if os.name == "nt":
        # Unlike os.replace, Windows os.rename refuses an existing destination.
        os.rename(temporary, output)
    else:
        os.link(temporary, output)


def publish_image(image, folder, stem, fmt, quality=85, before_publish=None, exif=b""):
    """Write an exclusive temp file, then publish atomically WITHOUT replacement.

    Windows rename refuses an existing destination; POSIX uses a no-replace link.
    There is no overwriting fallback.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bitdeck-", suffix=".part", dir=folder)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w+b") as stream:
            options = {"quality": quality} if fmt in {"JPEG", "WEBP"} else {"optimize": True}
            image.save(BoundedWriter(stream), format=fmt, **options, **({"exif": exif} if exif else {}))
            stream.flush()
            os.fsync(stream.fileno())
        if before_publish:
            before_publish()
        for index in range(10_000):
            suffix = "" if index == 0 else f" ({index})"
            output = folder / f"{stem}{suffix}{FORMATS[fmt]}"
            try:
                publish_no_replace(temporary, output)
                return output
            except FileExistsError:
                continue
        raise JobError("Too many existing output names. Choose another folder.")
    finally:
        temporary.unlink(missing_ok=True)


def run_job(job):
    if isinstance(job, dict):
        if job.get("operation") == "import_theme":
            from .skins import parse_wsz
            source = job.get("source")
            if not isinstance(source, str) or not source or len(source) > 32_000:
                raise JobError("Choose a classic .wsz skin file.")
            return parse_wsz(source)
        from .documents import OPERATIONS, run_document_job
        if job.get("operation") in OPERATIONS:
            return run_document_job(job)
    from PIL import Image, ImageDraw
    if not isinstance(job, dict) or job.get("operation") not in {"inspect", "export"}:
        raise JobError("Invalid job operation.")
    source = job.get("source")
    if not isinstance(source, str) or len(source) > 32_000:
        raise JobError("Invalid source path.")
    image, original_format, input_bytes, _, fingerprint = read_image(source)
    if job.get("expected_sha256") and job["expected_sha256"] != fingerprint:
        raise JobError("Source changed since preview. Select the image again before exporting.")
    original_size = list(image.size)
    fmt = job.get("format", "PNG")
    if fmt not in FORMATS:
        raise JobError("Unsupported output format.")
    quality = bounded_int(job.get("quality", 85), 1, 100, "Quality")
    long_edge = bounded_int(job.get("long_edge", 0), 0, MAX_SIDE, "Long edge")
    boxes = job.get("redactions", [])
    if not isinstance(boxes, list) or len(boxes) > 100:
        raise JobError("Use at most 100 redaction boxes.")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            raise JobError("Invalid redaction coordinates.")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise JobError("Redaction boxes must lie inside the image.")
        # Cover boundary pixels conservatively. Coordinates refer to oriented input.
        rectangle = (math.floor(x0 * image.width), math.floor(y0 * image.height),
                     min(image.width - 1, math.ceil(x1 * image.width)),
                     min(image.height - 1, math.ceil(y1 * image.height)))
        draw.rectangle(rectangle, fill=(0, 0, 0, 255) if image.mode == "RGBA" else (0, 0, 0))
    from .image_tools import edit_image, metadata
    image = edit_image(image, job)
    if long_edge and max(image.size) > long_edge:
        image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    policy = job.get("metadata_policy", "remove_all")
    if policy not in {"remove_all", "remove_gps", "keep_exif"}:
        raise JobError("Invalid metadata policy.")
    tags, exif = metadata(source, policy, fingerprint) if job["operation"] == "inspect" or policy != "remove_all" else ({}, b"")
    if job["operation"] == "inspect":
        import base64
        width, height = image.size
        image.thumbnail((1000, 640), Image.Resampling.LANCZOS)
        preview = io.BytesIO()
        image.save(preview, "PNG")
        return {"ok": True, "width": width, "height": height,
                "format": original_format, "input_bytes": input_bytes, "sha256": fingerprint,
                "metadata": tags, "preview": base64.b64encode(preview.getvalue()).decode("ascii")}
    if fmt == "JPEG" and image.mode == "RGBA":
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    # Lossy codecs can alter boundary pixels, but original pixels in boxes have
    # already been replaced before resizing/encoding.
    folder = job.get("output_dir")
    if not isinstance(folder, str) or not folder or len(folder) > 32_000:
        raise JobError("Choose an output folder.")
    stem = Path(source).stem[:120] + " - bitdeck"
    output = publish_image(image, folder, stem, fmt, quality, exif=exif)
    stat = output.stat()
    return {"ok": True, "output": str(output.resolve()), "input_bytes": input_bytes,
            "output_bytes": stat.st_size, "identity": [stat.st_ino, stat.st_size, stat.st_mtime_ns],
            "width": image.width, "height": image.height,
            "original_size": original_size, "redactions": len(boxes), "metadata_removed": policy == "remove_all", "metadata_policy": policy}
