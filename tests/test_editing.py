import io
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from bitdeck.core import run_job, JobError
from bitdeck.documents import page_indices


def test_image_crop_rotate_flip_and_preview_agree(tmp_path):
    source = tmp_path / "source.png"
    image = Image.new("RGB", (100, 60), "red")
    for x in range(50, 100):
        for y in range(60):
            image.putpixel((x, y), (0, 0, 255))
    image.save(source)
    before = source.read_bytes()
    job = dict(source=str(source), crop=[.5, 0, 1, 1], rotation=90, flip_horizontal=True, output_dir=str(tmp_path / "out"))
    result = run_job(dict(job, operation="export"))
    preview = run_job(dict(job, operation="inspect"))
    assert (result["width"], result["height"]) == (60, 50)
    assert (preview["width"], preview["height"]) == (60, 50)
    with Image.open(result["output"]) as output:
        assert output.getpixel((20, 20)) == (0, 0, 255)
    assert source.read_bytes() == before


def test_annotation_pixels_and_redaction_survive(tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (100, 100), "white").save(source)
    result = run_job(dict(operation="export", source=str(source), output_dir=str(tmp_path / "out"),
        redactions=[[0, 0, .2, .2]], annotations=[dict(kind="box", box=[.3, .3, .8, .8], color="#ff0000", width=4),
        dict(kind="arrow", box=[.7, .2, .3, .2], color="#0000ff", width=3)]))
    with Image.open(result["output"]) as output:
        assert output.getpixel((5, 5)) == (0, 0, 0)
        assert output.getpixel((30, 40)) == (255, 0, 0)
        assert output.getpixel((50, 20)) == (0, 0, 255)


def test_exif_gps_controls(tmp_path):
    source = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[271] = "Private Camera"
    exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0)}
    Image.new("RGB", (30, 20), "red").save(source, exif=exif)
    assert "GPS" in run_job(dict(operation="inspect", source=str(source)))["metadata"]
    for policy in ("remove_all", "remove_gps", "keep_exif"):
        result = run_job(dict(operation="export", source=str(source), format="JPEG", metadata_policy=policy, output_dir=str(tmp_path / policy)))
        with Image.open(result["output"]) as image:
            tags = image.getexif()
            assert (271 in tags) == (policy != "remove_all")
            assert (34853 in tags) == (policy == "keep_exif")


def pdf_fixture(tmp_path):
    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    for width in (100, 200, 300):
        writer.add_blank_page(width, 400)
    writer.add_metadata({"/Author": "Private"})
    writer.write(source)
    return source


def test_pdf_ranges_organize_and_metadata(tmp_path):
    source = pdf_fixture(tmp_path)
    info = run_job(dict(operation="pdf_inspect", source=str(source)))
    assert info["pages"] == 3 and info["metadata"]["/Author"] == "Private"
    assert not (tmp_path / "BitDeck").exists()
    result = run_job(dict(operation="pdf_organize", source=str(source), page_plan=[[0, 2, 90], [0, 0, 0], [0, 2, 180]]))
    reader = PdfReader(result["output"])
    assert [int(p.mediabox.width) for p in reader.pages] == [300, 100, 300]
    assert [p.rotation for p in reader.pages] == [90, 0, 180]
    result = run_job(dict(operation="pdf_split", source=str(source), page_range="3-2"))
    assert len(result["outputs"]) == 2
    assert int(PdfReader(result["outputs"][0]).pages[0].mediabox.width) == 300
    result = run_job(dict(operation="pdf_edit_metadata", source=str(source), metadata={"/Title": "New title"}, page_range="2"))
    assert PdfReader(result["output"]).metadata.title == "New title"
    assert len(PdfReader(result["output"]).pages) == 1


def test_encrypted_pdf_preview_and_unlock(tmp_path):
    source = pdf_fixture(tmp_path)
    encrypted = run_job(dict(operation="pdf_protect", source=str(source), password="password123"))["output"]
    with pytest.raises(JobError, match="password"):
        run_job(dict(operation="pdf_inspect", source=encrypted))
    result = run_job(dict(operation="pdf_preview", source=encrypted, input_password="password123", page=1))
    import base64
    with Image.open(io.BytesIO(base64.b64decode(result["preview"]))) as image:
        assert image.size == (200, 400)
    result = run_job(dict(operation="pdf_unlock", source=encrypted, input_password="password123"))
    assert not PdfReader(result["output"]).is_encrypted


@pytest.mark.parametrize("expression", ["0", "4", "1-999999999", "3--2", "nan", "1,", "-1"])
def test_invalid_ranges_bounded(expression):
    with pytest.raises(JobError):
        page_indices(expression, 3)


def test_pdf_changed_after_inspection(tmp_path):
    source = pdf_fixture(tmp_path)
    with pytest.raises(JobError, match="changed"):
        run_job(dict(operation="pdf_organize", source=str(source), page_plan=[[0, 0, 0]], fingerprints={str(source): "wrong"}))
