"""File families and the actions exposed by the cursor menu. No file parsing."""
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm",
                   ".yaml", ".yml", ".ini", ".cfg", ".toml", ".css", ".js", ".ts", ".py", ".sql"}


def category(path):
    extension = Path(path).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension == ".pdf":
        return "pdf"
    if extension == ".wsz":
        return "skin"
    if extension in TEXT_EXTENSIONS:
        return "text"
    return None


@dataclass(frozen=True)
class Action:
    title: str
    key: str
    hint: str


def actions_for(family, tools=False):
    groups = {
        ("skin", False): [("Apply skin", "import_theme", "Import this classic Winamp skin")],
        ("skin", True): [("Apply skin", "import_theme", "Use its colors and header artwork in BitDeck")],
        ("image", False): [("PNG", "image:PNG", "Lossless image"), ("JPEG", "image:JPEG", "Small, widely compatible"),
                           ("WEBP", "image:WEBP", "Compact web image"), ("PDF", "images_to_pdf", "One PDF from the dropped images")],
        ("image", True): [("Compress", "compress_image", "Save a compressed copy"), ("Resize", "resize_image", "Set the maximum long edge"),
                          ("Edit image", "image_controls", "Metadata, crop, rotate, flip and annotations"), ("Clean tags", "clean_image", "Rebuild a metadata-free image")],
        ("pdf", False): [("PNG", "pdf_to_png", "One PNG for each page"), ("JPEG", "pdf_to_jpeg", "One JPEG for each page"),
                         ("TXT", "pdf_to_text", "Extract the existing text layer; no OCR")],
        ("pdf", True): [("Page controls", "pdf_controls", "Preview, arrange, select pages, passwords and metadata"), ("Compress", "pdf_compress", "Lossless PDF stream compression"), ("Split", "pdf_split", "One PDF per page"),
                        ("Rotate", "pdf_rotate", "Rotate all pages"), ("Merge", "pdf_merge", "Combine PDFs in drop order"),
                        ("Protect", "pdf_protect", "AES-256 password encryption"), ("Images", "pdf_extract", "Extract embedded images"),
                        ("Clean info", "pdf_metadata", "Remove document Info/XMP; not full sanitization")],
        ("text", False): [("PDF", "text_to_pdf", "Paginated plain-text PDF"), ("UTF-8 TXT", "text_normalize", "Save as UTF-8 plain text")],
        ("text", True): [("PDF", "text_to_pdf", "Print the literal text; no markup execution"),
                          ("UTF-8 TXT", "text_normalize", "Normalize the text encoding")],
    }
    return [Action(*entry) for entry in groups.get((family, tools), [])]
