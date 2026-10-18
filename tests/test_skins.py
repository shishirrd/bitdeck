import base64
import io
import json
from pathlib import Path
import struct
import zipfile

from PIL import Image
import pytest

from bitdeck.core import JobError, run_job
from bitdeck.palette import DEFAULT
from bitdeck.skins import parse_wsz
from bitdeck.theming import validate_theme


def make_skin(path, extra=None, colors="[Text]\nNormal=#4dd0ff\nNormalBG=#080c14\nCurrent=#ffe38a\n"):
    bitmap = io.BytesIO()
    Image.new("RGB", (275, 116), (28, 47, 88)).save(bitmap, "BMP")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("VOLTAGE/MAIN.BMP", bitmap.getvalue())
        archive.writestr("VOLTAGE/PLEDIT.TXT", colors)
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return path


def test_classic_wsz_palette_and_rebuilt_header(tmp_path):
    source = make_skin(tmp_path / "Voltage.wsz", {"plugin.dll": b"not executed"})
    before = set(tmp_path.iterdir())
    result = run_job({"operation": "import_theme", "source": str(source)})
    assert result["ok"]
    theme = validate_theme(result["theme"])
    assert theme["name"] == "Voltage"
    assert theme["palette"]["accent"] == "#4dd0ff"
    assert theme["palette"]["display"] == "#080c14"
    with Image.open(io.BytesIO(base64.b64decode(theme["header_png"]))) as image:
        assert image.format == "PNG"
        assert image.size == (275, 14)
    assert set(tmp_path.iterdir()) == before  # no extraction


@pytest.mark.parametrize("name", ["../escape.bmp", "/absolute.bmp", "C:/escape.bmp", "nested/../../escape.bmp", "..\\escape.bmp"])
def test_unsafe_archive_member_paths_rejected(tmp_path, name):
    source = make_skin(tmp_path / "bad.wsz", {name: b"bad"})
    with pytest.raises(JobError, match="unsafe member path"):
        parse_wsz(source)


def test_duplicate_asset_names_rejected(tmp_path):
    source = make_skin(tmp_path / "bad.wsz", {"OTHER/main.bmp": b"fake"})
    with pytest.raises(JobError, match="duplicate"):
        parse_wsz(source)


def test_archive_file_count_limit(tmp_path):
    source = make_skin(tmp_path / "bad.wsz", {f"ignored{number}.txt": b"" for number in range(130)})
    with pytest.raises(JobError, match="file-count"):
        parse_wsz(source)


def test_modern_skin_or_arbitrary_zip_rejected(tmp_path):
    source = tmp_path / "modern.wsz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skin.xml", "<skin/>")
    with pytest.raises(JobError, match="MAIN.BMP"):
        parse_wsz(source)


def test_stylesheet_injection_does_not_leave_parser(tmp_path):
    source = make_skin(tmp_path / "badcolors.wsz", colors="[Text]\nNormal=url(file:///private)\nNormalBG=#080c14\n")
    result = parse_wsz(source)
    assert all(value.startswith("#") and len(value) == 7 for value in result["theme"]["palette"].values())


def test_cache_color_injection_rejected():
    theme = {"name": "Fake", "palette": {**DEFAULT, "accent": "red; image: url(secret)"}, "header_png": ""}
    with pytest.raises(ValueError, match="colors"):
        validate_theme(theme)


def test_cache_png_bomb_rejected_before_qt_decode():
    fake_png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 100000, 100000)
    theme = {"name": "Fake", "palette": dict(DEFAULT), "header_png": base64.b64encode(fake_png).decode()}
    with pytest.raises(ValueError, match="dimensions"):
        validate_theme(theme)
