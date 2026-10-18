import concurrent.futures
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, PngImagePlugin
import pytest

from bitdeck import core


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "sample.png"
    image = Image.new("RGBA", (240, 160), (200, 120, 60, 120))
    text = PngImagePlugin.PngInfo()
    text.add_text("Author", "Private person")
    text.add_text("XML:com.adobe.xmp", "Private location")
    image.save(path, pnginfo=text)
    return path


def request(source, **kwargs):
    return {"operation": "export", "source": str(source), "output_dir": str(source.parent / "out"),
            "format": "PNG", "quality": 85, "long_edge": 0, **kwargs}


def test_redaction_export_removes_metadata_and_preserves_source(source):
    before = source.read_bytes()
    result = core.run_job(request(source, redactions=[[.25, .25, .75, .75]]))
    assert source.read_bytes() == before
    with Image.open(result["output"]) as image:
        assert image.getpixel((100, 80)) == (0, 0, 0, 255)
        assert image.getpixel((0, 0)) == (200, 120, 60, 120)
        assert not image.info
        assert not image.getexif()
    stat = Path(result["output"]).stat()
    assert result["identity"] == [stat.st_ino, stat.st_size, stat.st_mtime_ns]


def test_concurrent_exports_never_overwrite(source):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: core.run_job(request(source)), range(16)))
    paths = [result["output"] for result in results]
    assert len(set(paths)) == 16
    assert all(Path(path).exists() for path in paths)
    assert not list((source.parent / "out").glob("*.part"))


def test_collision_at_publication_retries_without_overwrite(source):
    folder = source.parent / "out"
    image = Image.new("RGB", (3, 3))
    collision = folder / "result.png"
    result = core.publish_image(image, folder, "result", "PNG", before_publish=lambda: collision.write_bytes(b"keep me"))
    assert collision.read_bytes() == b"keep me"
    assert result.name == "result (1).png"


def test_unsupported_filesystem_fails_without_partial_output(source, monkeypatch):
    def fail(*_):
        raise OSError("Hard links unavailable")
    monkeypatch.setattr(core, "publish_no_replace", fail)
    with pytest.raises(OSError):
        core.run_job(request(source))
    assert list((source.parent / "out").iterdir()) == []


def test_output_limit_cleans_temporary_file(source, monkeypatch):
    monkeypatch.setattr(core, "MAX_OUTPUT", 12)
    with pytest.raises(core.JobError, match="output exceeds"):
        core.run_job(request(source))
    assert list((source.parent / "out").iterdir()) == []


def test_jpeg_native_encoder_cannot_bypass_output_limit(source, monkeypatch):
    monkeypatch.setattr(core, "MAX_OUTPUT", 20)
    with pytest.raises(core.JobError, match="output exceeds"):
        core.run_job(request(source, format="JPEG"))
    assert list((source.parent / "out").iterdir()) == []


def test_input_limit(source, monkeypatch):
    monkeypatch.setattr(core, "MAX_INPUT", 12)
    with pytest.raises(core.JobError, match="Input exceeds"):
        core.run_job(request(source))


def test_pixel_limit(source, monkeypatch):
    monkeypatch.setattr(core, "MAX_PIXELS", 100)
    with pytest.raises((core.JobError, Image.DecompressionBombError, Image.DecompressionBombWarning)):
        core.run_job(request(source))


@pytest.mark.parametrize("box", [[0, 0, 2, 1], [0, 0, float("nan"), 1], [True, 0, .5, .5], [.5, .5, .2, .2]])
def test_invalid_redaction_is_rejected(source, box):
    with pytest.raises(core.JobError):
        core.run_job(request(source, redactions=[box]))


def test_resize_and_jpeg_transparency(source):
    result = core.run_job(request(source, format="JPEG", long_edge=120))
    with Image.open(result["output"]) as image:
        assert image.size == (120, 80)
        assert image.mode == "RGB"
    result = core.run_job(request(source, long_edge=1000))
    assert [result["width"], result["height"]] == [240, 160]


def test_orientation_is_applied_before_redaction(tmp_path):
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Private author"
    image.save(path, exif=exif)
    result = core.run_job(request(path, redactions=[[0, 0, .5, .5]]))
    with Image.open(result["output"]) as out:
        assert out.size == (20, 40)
        assert out.getpixel((3, 3)) == (0, 0, 0)
        assert not out.getexif()


def test_format_is_detected_from_bytes(source):
    disguised = source.with_suffix(".jpg")
    disguised.write_bytes(source.read_bytes())
    result = core.run_job({"operation": "inspect", "source": str(disguised)})
    assert result["format"] == "PNG"


def test_source_changed_since_preview_is_rejected(source):
    preview = core.run_job({"operation": "inspect", "source": str(source)})
    Image.new("RGB", (240, 160), "blue").save(source)
    with pytest.raises(core.JobError, match="Source changed"):
        core.run_job(request(source, expected_sha256=preview["sha256"]))


def test_animation_rejected(tmp_path):
    path = tmp_path / "animated.webp"
    Image.new("RGB", (20, 20), "red").save(path, save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")], duration=100)
    with pytest.raises(core.JobError, match="Animated"):
        core.run_job(request(path))


def test_worker_rejects_bad_protocol():
    process = subprocess.run([sys.executable, "-m", "bitdeck.worker"], input=b"[]\n", capture_output=True, timeout=10)
    result = json.loads(process.stdout)
    assert process.returncode == 1
    assert result["ok"] is False


def test_worker_has_no_image_import_before_request():
    # Static contract: the worker itself has no third-party top-level imports.
    import ast
    tree = ast.parse((Path(__file__).parents[1] / "bitdeck" / "worker.py").read_text())
    names = [node.names[0].name for node in tree.body if isinstance(node, ast.Import)]
    assert names == ["json", "sys"]
