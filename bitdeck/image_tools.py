"""Bounded image metadata and edits. Worker only; coordinates use oriented input."""
import io
import math
import re
from pathlib import Path

from .core import JobError, MAX_INPUT, bounded_int


def metadata(source, policy="remove_all", expected=""):
    from PIL import Image, ExifTags
    from .documents import read_bytes
    raw = read_bytes(source)
    import hashlib
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise JobError("Source changed while reading metadata. Reload it before exporting.")
    if len(raw) > MAX_INPUT:
        raise JobError("Input exceeds 64 MiB.")
    with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG", "WEBP"]) as image:
        exif = image.getexif()
        rows = {ExifTags.TAGS.get(key, str(key)): str(value)[:1024] for key, value in list(exif.items())[:200]}
        if 34853 in exif:
            rows["GPS"] = str(exif.get_ifd(34853))[:2048]
        for key, value in list(image.info.items())[:100]:
            if key not in {"exif", "icc_profile"}:
                rows[str(key)[:100]] = str(value)[:1024]
        # Rebuild common descriptive/capture fields, rather than copying opaque
        # maker notes or original thumbnails that may expose unedited pixels.
        kept = Image.Exif()
        for key in (269, 270, 271, 272, 282, 283, 296, 305, 306, 315, 33432):
            if key in exif:
                kept[key] = exif[key]
        if 34665 in exif:
            capture = exif.get_ifd(34665)
            allowed = (33434, 33437, 34850, 34855, 36864, 36867, 36868, 37377, 37378, 37380, 37383, 37385, 37386, 41986, 41987, 41989)
            kept[34665] = {key: capture[key] for key in allowed if key in capture}
        if policy == "keep_exif" and 34853 in exif:
            kept[34853] = exif.get_ifd(34853)
        return rows, kept.tobytes() if policy in {"keep_exif", "remove_gps"} else b""


def coordinates(value, rectangle=True):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in value):
        raise JobError("Coordinates must be four finite fractions between zero and one.")
    if rectangle and (value[0] >= value[2] or value[1] >= value[3]):
        raise JobError("Selection must have positive width and height.")
    return value


def edit_image(image, job):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    annotations = job.get("annotations", [])
    if not isinstance(annotations, list) or len(annotations) > 100:
        raise JobError("Use at most 100 annotations.")
    draw = ImageDraw.Draw(image)
    for entry in annotations:
        if not isinstance(entry, dict):
            raise JobError("Invalid annotation.")
        kind = entry.get("kind")
        x0, y0, x1, y1 = coordinates(entry.get("box"), rectangle=kind not in {"arrow", "marker"})
        color = entry.get("color", "#ffcc00")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise JobError("Choose an RGB annotation color.")
        width = bounded_int(entry.get("width", 4), 1, 100, "Stroke width")
        a, b = (round(x0 * (image.width - 1)), round(y0 * (image.height - 1))), (round(x1 * (image.width - 1)), round(y1 * (image.height - 1)))
        if kind == "box":
            draw.rectangle((*a, *b), outline=color, width=width)
        elif kind in {"arrow", "marker"}:
            draw.line((a, b), fill=color, width=width)
            if kind == "arrow":
                angle = math.atan2(b[1] - a[1], b[0] - a[0])
                length = max(10, width * 4)
                tips = [(b[0] - length * math.cos(angle + offset), b[1] - length * math.sin(angle + offset)) for offset in (-.5, .5)]
                draw.polygon([b, *tips], fill=color)
        elif kind in {"text", "number"}:
            text = entry.get("text", "1")
            if not isinstance(text, str) or not 1 <= len(text) <= 500:
                raise JobError("Annotation text must contain 1–500 characters.")
            size = bounded_int(entry.get("size", 24), 8, 256, "Font size")
            import os
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
            font = ImageFont.truetype(str(font_path), size) if font_path.is_file() else ImageFont.load_default(size=size)
            draw.text(a, text, fill=color, font=font, stroke_width=1)
        else:
            raise JobError("Unsupported annotation tool.")
    crop = job.get("crop")
    if crop is not None:
        x0, y0, x1, y1 = coordinates(crop)
        image = image.crop((math.floor(x0 * image.width), math.floor(y0 * image.height), math.ceil(x1 * image.width), math.ceil(y1 * image.height)))
    rotation = job.get("rotation", 0)
    if type(rotation) is not int or rotation not in {0, 90, 180, 270}:
        raise JobError("Rotation must be 0, 90, 180 or 270 degrees.")
    if rotation:
        image = image.rotate(-rotation, expand=True)
    if job.get("flip_horizontal"):
        image = ImageOps.mirror(image)
    if job.get("flip_vertical"):
        image = ImageOps.flip(image)
    return image
