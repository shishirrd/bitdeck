import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest
from reportlab.pdfgen.canvas import Canvas

from bitdeck import core, documents
from bitdeck.actions import actions_for, category


def make_pdf(path, pages=2, image=False):
    canvas = Canvas(str(path), pagesize=(300, 400))
    canvas.setAuthor("Private Author")
    for index in range(pages):
        canvas.drawString(20, 350, f"Page {index + 1}: hello BitDeck")
        if image:
            from reportlab.lib.utils import ImageReader
            canvas.drawImage(ImageReader(Image.new("RGB", (30, 20), "red")), 20, 40, 100, 60)
        canvas.showPage()
    canvas.save()
    return path


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "report.pdf")


def job(path, operation, **options):
    return {"operation": operation, "source": str(path), "output_dir": str(path.parent / "out"), **options}


@pytest.mark.parametrize("operation,extension", [("pdf_to_png", ".png"), ("pdf_to_jpeg", ".jpg")])
def test_pdf_page_images_and_source_unchanged(pdf, operation, extension):
    before = pdf.read_bytes()
    result = core.run_job(job(pdf, operation, dpi=72))
    assert len(result["outputs"]) == 2
    assert pdf.read_bytes() == before
    for name in result["outputs"]:
        assert Path(name).suffix == extension
        with Image.open(name) as image:
            assert image.size == (300, 400)


def test_pdf_text_layer(pdf):
    result = core.run_job(job(pdf, "pdf_to_text"))
    text = Path(result["output"]).read_text(encoding="utf-8")
    assert "Page 1: hello BitDeck" in text
    assert "Page 2: hello BitDeck" in text


def test_split_merge_order(pdf):
    split = core.run_job(job(pdf, "pdf_split"))
    assert len(split["outputs"]) == 2
    merged = core.run_job(job(pdf, "pdf_merge", sources=list(reversed(split["outputs"]))))
    reader = PdfReader(merged["output"])
    assert "Page 2" in reader.pages[0].extract_text()
    assert "Page 1" in reader.pages[1].extract_text()


def test_rotation_and_compression(pdf):
    result = core.run_job(job(pdf, "pdf_rotate", degrees=90))
    assert all(page.rotation == 90 for page in PdfReader(result["output"]).pages)
    compressed = core.run_job(job(pdf, "pdf_compress"))
    assert len(PdfReader(compressed["output"]).pages) == 2


def test_password_encryption_is_aes256(pdf):
    result = core.run_job(job(pdf, "pdf_protect", password="eight-or-more-characters"))
    reader = PdfReader(result["output"])
    assert reader.is_encrypted
    assert reader.trailer["/Encrypt"]["/Length"] == 256
    assert reader.decrypt("incorrect") == 0
    assert reader.decrypt("eight-or-more-characters") != 0
    assert len(reader.pages) == 2


def test_document_info_removed(pdf):
    result = core.run_job(job(pdf, "pdf_metadata"))
    assert not PdfReader(result["output"]).metadata


def test_extract_embedded_image(tmp_path):
    source = make_pdf(tmp_path / "image.pdf", pages=1, image=True)
    result = core.run_job(job(source, "pdf_extract"))
    assert len(result["outputs"]) == 1
    with Image.open(result["output"]) as image:
        assert image.size == (30, 20)
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert not image.info


def test_render_budget_and_rollback(pdf, monkeypatch):
    monkeypatch.setattr(documents, "MAX_RENDER_PAGES", 1)
    with pytest.raises(core.JobError, match="50 PDF pages"):
        core.run_job(job(pdf, "pdf_to_png"))
    assert not list((pdf.parent / "out").iterdir())


def test_partial_split_failure_rolls_back(pdf, monkeypatch):
    monkeypatch.setattr(documents, "MAX_OUTPUT_FILES", 1)
    with pytest.raises(core.JobError, match="file limit"):
        core.run_job(job(pdf, "pdf_split"))
    assert not list((pdf.parent / "out").iterdir())


def test_combined_output_budget(pdf, monkeypatch):
    monkeypatch.setattr(documents, "MAX_OUTPUT", 12)
    with pytest.raises(core.JobError, match="Combined outputs"):
        core.run_job(job(pdf, "pdf_split"))
    assert not list((pdf.parent / "out").iterdir())


def test_text_to_pdf_and_normalization(tmp_path):
    source = tmp_path / "notes.md"
    content = "# Literal markdown\n<script>not executed</script>\nCafé\n"
    source.write_text(content, encoding="utf-16")
    result = core.run_job(job(source, "text_to_pdf"))
    extracted = "".join(page.extract_text() for page in PdfReader(result["output"]).pages)
    assert "# Literal markdown" in extracted
    assert "<script>not executed</script>" in extracted
    normalized = core.run_job(job(source, "text_normalize"))
    assert Path(normalized["output"]).read_text(encoding="utf-8") == content


def test_multiple_images_make_one_pdf(tmp_path):
    sources = []
    for index in range(3):
        path = tmp_path / f"image{index}.png"
        Image.new("RGB", (80 + index, 60), "blue").save(path)
        sources.append(str(path))
    result = core.run_job(job(Path(sources[0]), "images_to_pdf", sources=sources))
    assert len(PdfReader(result["output"]).pages) == 3
    assert result["pages"] == 3


def test_binary_and_invalid_pdf_are_rejected(tmp_path):
    source = tmp_path / "binary.txt"
    source.write_bytes(b"\x00binary")
    with pytest.raises(core.JobError, match="binary data"):
        core.run_job(job(source, "text_to_pdf"))
    source = tmp_path / "pretend.pdf"
    source.write_text("not a PDF")
    with pytest.raises(core.JobError, match="PDF header"):
        core.run_job(job(source, "pdf_split"))


def test_family_actions_exclude_word():
    assert category("file.docx") is None
    assert category("file.pdf") == "pdf"
    assert category("file.md") == "text"
    assert {action.key for action in actions_for("pdf", True)} >= {"pdf_merge", "pdf_split", "pdf_protect"}
    assert {action.key for action in actions_for("text")} == {"text_to_pdf", "text_normalize"}
