"""PDF / text / image-to-PDF operations, loaded only inside worker processes.

No Office automation, shell commands, web fetches, or HTML interpretation.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import tempfile
import textwrap

from .core import JobError, MAX_INPUT, MAX_OUTPUT, MAX_PIXELS, MAX_SIDE, BoundedWriter, bounded_int, publish_no_replace

MAX_PAGES = 200
MAX_RENDER_PAGES = 50
MAX_OUTPUT_FILES = 200
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 500_000
OPERATIONS = {"pdf_to_png", "pdf_to_jpeg", "pdf_to_text", "pdf_compress", "pdf_split", "pdf_rotate", "pdf_merge",
              "pdf_protect", "pdf_extract", "pdf_metadata", "pdf_inspect", "pdf_preview", "pdf_organize", "pdf_unlock", "pdf_edit_metadata", "text_to_pdf", "text_normalize", "images_to_pdf"}


from .page_ranges import page_indices as _page_indices


def page_indices(expression, count):
    try:
        return _page_indices(expression, count)
    except ValueError as error:
        raise JobError(str(error)) from error

def read_bytes(path, limit=MAX_INPUT):
    path = Path(path)
    if not path.is_file():
        raise JobError("Choose an existing file.")
    with path.open("rb") as source:
        if os.fstat(source.fileno()).st_size > limit:
            raise JobError(f"Input exceeds the {limit // (1024 * 1024)} MiB limit.")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise JobError("Input exceeds its byte limit.")
    return data


class Outputs:
    """Atomic no-replace publication with an aggregate job budget and rollback."""
    def __init__(self, folder, stem):
        self.folder = Path(folder)
        self.stem = stem[:120]
        self.paths = []
        self.identities = []
        self.total = 0

    def add(self, extension, write, label=""):
        self.folder.mkdir(parents=True, exist_ok=True)
        if len(self.paths) >= MAX_OUTPUT_FILES:
            raise JobError("Output file limit reached (200 files per job).")
        fd, name = tempfile.mkstemp(prefix=".bitdeck-", suffix=".part", dir=self.folder)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w+b") as stream:
                write(BoundedWriter(stream))
                stream.flush()
                os.fsync(stream.fileno())
                size = os.fstat(stream.fileno()).st_size
            if self.total + size > MAX_OUTPUT:
                raise JobError("Combined outputs exceed the 64 MiB job limit.")
            for index in range(10_000):
                suffix = "" if index == 0 else f" ({index})"
                candidate = self.folder / f"{self.stem}{label}{suffix}{extension}"
                try:
                    publish_no_replace(temporary, candidate)
                    break
                except FileExistsError:
                    continue
            else:
                raise JobError("Too many output name collisions.")
            stat = candidate.stat()
            self.paths.append(candidate)
            self.identities.append([stat.st_ino, stat.st_size, stat.st_mtime_ns])
            self.total += size
            return candidate
        finally:
            temporary.unlink(missing_ok=True)

    def rollback(self):
        for path, identity in zip(self.paths, self.identities):
            try:
                stat = path.stat()
                if [stat.st_ino, stat.st_size, stat.st_mtime_ns] == identity:
                    path.unlink()
            except OSError:
                pass


def pdf_reader(data, password=""):
    from pypdf import PdfReader
    if not data.lstrip()[:1024].startswith(b"%PDF-"):
        raise JobError("This file does not contain a supported PDF header.")
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(password):
        raise JobError("This PDF needs a valid input password.")
    if not 0 < len(reader.pages) <= MAX_PAGES:
        raise JobError("PDFs must contain 1–200 pages.")
    return reader


def text_content(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError as error:
                raise JobError("Text must be UTF-8, BOM-marked UTF-16, or Windows-1252.") from error
    if len(text) > MAX_TEXT_CHARS:
        raise JobError("Text exceeds the 500,000-character limit.")
    if any(ord(character) < 32 and character not in "\r\n\t\f" for character in text):
        raise JobError("This looks like binary data, not plain text.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text_pdf(stream, text):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = "Courier"
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"
    if font_path.is_file():
        pdfmetrics.registerFont(TTFont("BitDeckMono", str(font_path)))
        font = "BitDeckMono"
    canvas = Canvas(stream, pagesize=(612, 792), pageCompression=1)
    canvas.setTitle("")
    canvas.setAuthor("")
    canvas.setCreator("BitDeck")
    canvas.setFont(font, 10)
    y, pages = 744, 1
    for line in text.split("\n"):
        for section in textwrap.wrap(line.expandtabs(4), width=85, replace_whitespace=False, drop_whitespace=False) or [""]:
            if y < 48:
                canvas.showPage()
                pages += 1
                if pages > MAX_PAGES:
                    raise JobError("Text would create more than 200 PDF pages.")
                canvas.setFont(font, 10)
                y = 744
            canvas.drawString(48, y, section)
            y -= 14
    canvas.save()


def run_document_job(job):
    from pypdf import PdfWriter
    operation = job.get("operation")
    if operation not in OPERATIONS:
        raise JobError("Unsupported document action.")
    sources = job.get("sources") or [job.get("source")]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 50 or any(not isinstance(path, str) or not path or len(path) > 32_000 for path in sources):
        raise JobError("Use 1–50 input files per job.")
    folder = job.get("output_dir") or str(Path(sources[0]).parent / "BitDeck")
    if not isinstance(folder, str) or not folder or len(folder) > 32_000:
        raise JobError("Choose an output folder.")
    outputs = Outputs(folder, Path(sources[0]).stem + " - bitdeck")
    total_input = 0
    pages_processed = 0
    try:
        if operation == "images_to_pdf":
            from reportlab.pdfgen.canvas import Canvas
            from reportlab.lib.utils import ImageReader
            from .core import read_image

            def write(stream):
                nonlocal total_input, pages_processed
                canvas = Canvas(stream, pageCompression=1)
                canvas.setAuthor("")
                canvas.setTitle("")
                canvas.setCreator("BitDeck")
                for source in sources:
                    image, _, count, _, _ = read_image(source)
                    total_input += count
                    if total_input > MAX_INPUT:
                        raise JobError("Combined input exceeds 64 MiB.")
                    # One image at a time; avoid collecting decoded originals.
                    scale = min(1, 720 / max(image.size))
                    width, height = image.width * scale, image.height * scale
                    canvas.setPageSize((width, height))
                    canvas.drawImage(ImageReader(image), 0, 0, width, height, mask="auto")
                    canvas.showPage()
                    pages_processed += 1
                    image.close()
                canvas.save()
            outputs.add(".pdf", write)
        elif operation in {"text_to_pdf", "text_normalize"}:
            if len(sources) != 1:
                raise JobError("Convert one text file per job.")
            raw = read_bytes(sources[0], MAX_TEXT_BYTES)
            total_input = len(raw)
            text = text_content(raw)
            if operation == "text_to_pdf":
                outputs.add(".pdf", lambda stream: write_text_pdf(stream, text))
            else:
                outputs.add(".txt", lambda stream: stream.write(text.encode("utf-8")))
        else:
            readers = []
            raw_inputs = []
            for source in sources:
                raw = read_bytes(source)
                total_input += len(raw)
                if total_input > MAX_INPUT:
                    raise JobError("Combined input exceeds 64 MiB.")
                passwords = job.get("input_passwords", {})
                password = passwords.get(source, job.get("input_password", "")) if isinstance(passwords, dict) else ""
                readers.append(pdf_reader(raw, password))
                expected = job.get("fingerprints", {}).get(source)
                if expected and hashlib.sha256(raw).hexdigest() != expected:
                    raise JobError("A PDF changed since inspection. Reload it before exporting.")
                raw_inputs.append(raw)
            if operation not in {"pdf_merge", "pdf_organize"} and len(readers) != 1:
                raise JobError("Use one PDF for this action.")
            pages_processed = sum(len(reader.pages) for reader in readers)
            if pages_processed > MAX_PAGES:
                raise JobError("Combined PDF exceeds 200 pages.")
            reader = readers[0]
            selected = page_indices(job.get("page_range", ""), len(reader.pages))
            if operation == "pdf_inspect":
                return {"ok": True, "pages": len(reader.pages), "sha256": hashlib.sha256(raw_inputs[0]).hexdigest(),
                        "metadata": {str(k): str(v)[:2048] for k, v in list((reader.metadata or {}).items())[:100]},
                        "sizes": [[float(p.mediabox.width), float(p.mediabox.height)] for p in reader.pages]}
            if operation == "pdf_preview":
                import base64
                import pypdfium2 as pdfium
                index = bounded_int(job.get("page", 0), 0, len(reader.pages) - 1, "Page")
                with pdfium.PdfDocument(raw_inputs[0], password=password) as document:
                    page = document[index]
                    try:
                        width, height = page.get_size()
                        if width <= 0 or height <= 0:
                            raise JobError("Invalid page size.")
                        bitmap = page.render(scale=min(1, 900 / max(width, height)))
                        try:
                            image = bitmap.to_pil()
                            preview = io.BytesIO()
                            image.save(preview, "PNG")
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                return {"ok": True, "preview": base64.b64encode(preview.getvalue()).decode("ascii"), "page": index}
            pages_processed = len(selected) if operation not in {"pdf_merge", "pdf_organize"} else pages_processed
            if operation in {"pdf_to_png", "pdf_to_jpeg"}:
                import pypdfium2 as pdfium
                if pages_processed > MAX_RENDER_PAGES:
                    raise JobError("Image export is limited to 50 PDF pages per job.")
                dpi = bounded_int(job.get("dpi", 150), 72, 300, "DPI")
                document = pdfium.PdfDocument(raw_inputs[0], password=password)
                try:
                    for index in selected:
                        page = document[index]
                        try:
                            width, height = page.get_size()
                            scale = dpi / 72
                            if max(width, height) * scale > MAX_SIDE or width * height * scale * scale > MAX_PIXELS:
                                raise JobError("Rendered PDF page exceeds the image pixel limit.")
                            bitmap = page.render(scale=scale)
                            try:
                                image = bitmap.to_pil().convert("RGB")
                                fmt, extension = ("PNG", ".png") if operation == "pdf_to_png" else ("JPEG", ".jpg")
                                outputs.add(extension, lambda stream, im=image: im.save(stream, fmt, **({"quality": 90} if fmt == "JPEG" else {})), f" - page {index + 1:03}")
                                image.close()
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                finally:
                    document.close()
            elif operation == "pdf_to_text":
                # PDFium extracts text without expanding pypdf content streams in Python.
                import pypdfium2 as pdfium
                document = pdfium.PdfDocument(raw_inputs[0], password=password)
                try:
                    def write(stream):
                        for index in selected:
                            page = document[index]
                            try:
                                text_page = page.get_textpage()
                                try:
                                    stream.write(text_page.get_text_range().encode("utf-8"))
                                    stream.write(b"\n\f\n")
                                finally:
                                    text_page.close()
                            finally:
                                page.close()
                    outputs.add(".txt", write)
                finally:
                    document.close()
            elif operation == "pdf_extract":
                count = 0
                for index in selected:
                    page = reader.pages[index]
                    for image in page.images:
                        count += 1
                        # Decode/rebuild embedded images; never trust their suggested names.
                        from PIL import Image
                        with Image.open(io.BytesIO(image.data)) as embedded:
                            if embedded.width * embedded.height > MAX_PIXELS or max(embedded.size) > MAX_SIDE:
                                raise JobError("Embedded image exceeds the pixel budget.")
                            clean = Image.new("RGB", embedded.size)
                            clean.paste(embedded.convert("RGB"))
                            outputs.add(".png", lambda stream, im=clean: im.save(stream, "PNG"), f" - image {count:03}")
                if not count:
                    raise JobError("No extractable images found in this PDF.")
            elif operation == "pdf_split":
                for index in selected:
                    page = reader.pages[index]
                    writer = PdfWriter()
                    writer.add_page(page)
                    outputs.add(".pdf", writer.write, f" - page {index + 1:03}")
            else:
                writer = PdfWriter()
                if operation == "pdf_organize":
                    plan = job.get("page_plan")
                    if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PAGES:
                        raise JobError("Keep 1–200 pages in the output.")
                    for entry in plan:
                        if not isinstance(entry, list) or len(entry) != 3:
                            raise JobError("Invalid page arrangement.")
                        source_index = bounded_int(entry[0], 0, len(readers) - 1, "Document")
                        page_index = bounded_int(entry[1], 0, len(readers[source_index].pages) - 1, "Page")
                        rotation = entry[2]
                        if type(rotation) is not int or rotation not in {0, 90, 180, 270}:
                            raise JobError("Invalid page rotation.")
                        writer.add_page(readers[source_index].pages[page_index]).rotate(rotation)
                    pages_processed = len(plan)
                else:
                    for item in readers:
                        for index in (range(len(item.pages)) if operation == "pdf_merge" else selected):
                            writer.add_page(item.pages[index])
                if operation == "pdf_rotate":
                    degrees = job.get("degrees", 90)
                    if type(degrees) is not int or degrees not in {90, 180, 270}:
                        raise JobError("Rotation must be 90, 180 or 270 degrees.")
                    for page in writer.pages:
                        page.rotate(degrees)
                elif operation == "pdf_compress":
                    for page in writer.pages:
                        page.compress_content_streams()
                    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
                elif operation == "pdf_protect":
                    password = job.get("password")
                    if not isinstance(password, str) or not 8 <= len(password) <= 128:
                        raise JobError("Use a password of 8–128 characters.")
                    writer.encrypt(password, algorithm="AES-256")
                elif operation == "pdf_metadata":
                    writer.metadata = None
                    for page in writer.pages:
                        if "/Metadata" in page:
                            del page["/Metadata"]
                elif operation == "pdf_edit_metadata":
                    values = job.get("metadata", {})
                    if not isinstance(values, dict) or any(k not in {"/Title", "/Author", "/Subject", "/Keywords"} or not isinstance(v, str) or len(v) > 2048 for k, v in values.items()):
                        raise JobError("Invalid PDF metadata fields.")
                    writer.add_metadata(values)
                outputs.add(".pdf", writer.write)
        return {"ok": True, "output": str(outputs.paths[0].resolve()),
                "outputs": [str(path.resolve()) for path in outputs.paths], "identities": outputs.identities,
                "identity": outputs.identities[0], "input_bytes": total_input, "output_bytes": outputs.total,
                "pages": pages_processed, "operation": operation}
    except Exception:
        outputs.rollback()
        raise
