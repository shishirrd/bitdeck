"""Bounded classic Winamp .wsz import. Parses in the resource-limited worker.

No archive members are extracted to disk; no scripts/plugins/fonts/cursors load.
Only rebuilt PNG header pixels and validated color values leave the worker.
"""
import base64
from collections import Counter
import configparser
import io
from pathlib import Path, PurePosixPath
import re
import stat
import warnings
import zipfile

from .core import JobError
from .palette import DEFAULT

MAX_ARCHIVE = 8 * 1024 * 1024
MAX_EXPANDED = 24 * 1024 * 1024
MAX_MEMBER = 4 * 1024 * 1024
MAX_MEMBERS = 128
HEX = re.compile(r"#?[0-9a-fA-F]{6}\Z")


def luminance(rgb):
    return sum(value * weight for value, weight in zip(rgb, (.2126, .7152, .0722))) / 255


def contrast_color(background):
    return "#121212" if luminance(background) > .5 else "#efefef"


def parse_wsz(source):
    from PIL import Image
    from .documents import read_bytes
    raw = read_bytes(source, MAX_ARCHIVE)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as error:
        raise JobError("This .wsz is not a readable classic-skin ZIP archive.") from error
    assets = {}
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS or sum(item.file_size for item in infos) > MAX_EXPANDED:
            raise JobError("Skin archive exceeds its file-count or expanded-size limit.")
        for item in infos:
            name = item.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
                raise JobError("Skin archive contains an unsafe member path.")
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or item.flag_bits & 1:
                raise JobError("Skin archive contains a link or encrypted member.")
            if item.file_size > MAX_MEMBER or (item.file_size > 100_000 and item.file_size > max(1, item.compress_size) * 200):
                raise JobError("Skin archive contains an oversized or over-compressed member.")
            basename = path.name.lower()
            if basename in {"main.bmp", "titlebar.bmp", "pledit.txt"}:
                if basename in assets:
                    raise JobError("Skin has ambiguous duplicate asset names.")
                assets[basename] = archive.read(item)
    if "main.bmp" not in assets:
        raise JobError("Classic skins need MAIN.BMP. Modern .wal skins are not supported.")
    palette = dict(DEFAULT)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(assets["main.bmp"]), formats=["BMP"]) as image:
            if image.width < 64 or image.height < 32 or image.width > 1024 or image.height > 1024:
                raise JobError("MAIN.BMP dimensions must be between 64×32 and 1024×1024.")
            image.load()
            clean = image.convert("RGB")
            common = Counter(clean.resize((64, 32)).getdata()).most_common(100)
            # Favor neutral chassis colors over bright glyphs in the sprite sheet.
            chassis = next((rgb for rgb, _ in common if .08 < luminance(rgb) < .7 and max(rgb) - min(rgb) < 90), common[0][0])
            palette["panel"] = "#%02x%02x%02x" % chassis
            palette["control"] = "#%02x%02x%02x" % tuple(min(240, int(value * 1.18) + 10) for value in chassis)
            palette["text"] = contrast_color(chassis)
            palette["border"] = "#%02x%02x%02x" % tuple(min(255, value + 60) for value in chassis)
            palette["muted"] = "#%02x%02x%02x" % tuple(int(value * .25 + (230 if palette["text"] == "#efefef" else 20) * .75) for value in chassis)
            saturated = [rgb for rgb, _ in common if max(rgb) - min(rgb) > 85 and .2 < luminance(rgb) < .9]
            if saturated:
                palette["accent"] = "#%02x%02x%02x" % saturated[0]
            header = clean.crop((0, 0, min(275, clean.width), min(14, clean.height)))
    if "titlebar.bmp" in assets:
        with Image.open(io.BytesIO(assets["titlebar.bmp"]), formats=["BMP"]) as titlebar:
            if titlebar.width > 1024 or titlebar.height > 1024:
                raise JobError("TITLEBAR.BMP exceeds the bitmap dimension limit.")
            titlebar.load()
            header = titlebar.convert("RGB").crop((0, 0, min(275, titlebar.width), min(14, titlebar.height)))
    if "pledit.txt" in assets:
        if len(assets["pledit.txt"]) > 32_768:
            raise JobError("Playlist color settings exceed 32 KiB.")
        configuration = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            configuration.read_string(assets["pledit.txt"].decode("utf-8-sig", "replace"))
        except configparser.Error:
            configuration = configparser.ConfigParser(interpolation=None)
        section = next((name for name in configuration.sections() if name.lower() == "text"), None)
        if section:
            for option, role in {"normal": "accent", "normalbg": "display", "current": "secondary"}.items():
                value = configuration.get(section, option, fallback="").strip()
                if HEX.fullmatch(value):
                    palette[role] = "#" + value.lstrip("#").lower()
    # Never allow the display foreground to vanish into its background.
    from PIL import ImageColor
    if abs(luminance(ImageColor.getrgb(palette["accent"])) - luminance(ImageColor.getrgb(palette["display"]))) < .25:
        palette["accent"] = contrast_color(ImageColor.getrgb(palette["display"]))
    if abs(luminance(ImageColor.getrgb(palette["secondary"])) - luminance(ImageColor.getrgb(palette["display"]))) < .25:
        palette["secondary"] = contrast_color(ImageColor.getrgb(palette["display"]))
    encoded = io.BytesIO()
    header.save(encoded, "PNG")
    return {"ok": True, "operation": "import_theme", "theme": {
        "name": Path(source).stem[:80], "palette": palette,
        "header_png": base64.b64encode(encoded.getvalue()).decode("ascii"),
        "kind": "classic-wsz-adaptation"}}
