"""Apply safe .wsz-derived colors/header pixels; remember only validated data."""
import base64
import json
from pathlib import Path
import re
import struct

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths
from PySide6.QtGui import QPixmap

from . import palette

MAX_CACHE = 256 * 1024


def validate_theme(theme):
    if not isinstance(theme, dict) or not isinstance(theme.get("name"), str) or len(theme["name"]) > 80:
        raise ValueError("Invalid theme name")
    colors = theme.get("palette")
    if not isinstance(colors, dict) or set(colors) != set(palette.DEFAULT) or any(not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value) for value in colors.values()):
        raise ValueError("Invalid theme colors")
    image = theme.get("header_png", "")
    if not isinstance(image, str) or len(image) > 128 * 1024:
        raise ValueError("Invalid theme header")
    raw = base64.b64decode(image, validate=True)
    if raw and (not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > 96 * 1024):
        raise ValueError("Invalid theme header")
    if raw:
        if len(raw) < 24 or raw[12:16] != b"IHDR":
            raise ValueError("Invalid PNG header")
        width, height = struct.unpack(">II", raw[16:24])
        if not (1 <= width <= 275 and 1 <= height <= 14):
            raise ValueError("Invalid theme header dimensions")
    return {"name": theme["name"], "palette": dict(colors), "header_png": image,
            "kind": "classic-wsz-adaptation"}


class ThemeManager:
    def __init__(self, application, menu, cache=None):
        self.application, self.menu = application, menu
        base = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        self.cache = Path(cache) if cache else base / "theme.json"
        self.current = {"name": "BitDeck", "palette": dict(palette.DEFAULT), "header_png": ""}
        from .app import STYLE
        self.original_style = STYLE
        try:
            if self.cache.is_file() and self.cache.stat().st_size <= MAX_CACHE:
                self.apply(json.loads(self.cache.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def apply(self, theme, persist=False):
        theme = validate_theme(theme)
        pixmap = QPixmap()
        raw = base64.b64decode(theme["header_png"])
        if raw:
            if not pixmap.loadFromData(raw, "PNG") or not (1 <= pixmap.width() <= 275 and 1 <= pixmap.height() <= 14):
                raise ValueError("Invalid theme header dimensions")
        self.current = theme
        palette.ACTIVE.clear()
        palette.ACTIVE.update(theme["palette"])
        # Replace only known built-in color tokens, never interpolate skin text
        # into executable stylesheets or resource paths.
        colors = theme["palette"]
        from PySide6.QtGui import QColor
        selected_text = "#101010" if QColor(colors["accent"]).lightness() > 130 else "#ffffff"
        replacements = {"#22252b": colors["panel"], "#282c33": colors["panel"], "#3b4048": colors["control"],
                        "#deded9": colors["text"], "#c4ee70": colors["accent"], "#e8b768": colors["secondary"],
                        "#101610": colors["display"], "#14181d": colors["display"], "#13181b": colors["display"],
                        "#92989f": colors["muted"], "#626975": colors["border"], "#151c10": selected_text,
                        "#a2ba70": colors["accent"]}
        pattern = re.compile("|".join(re.escape(color) for color in replacements), re.IGNORECASE)
        stylesheet = pattern.sub(lambda match: replacements[match.group().lower()], self.original_style)
        stylesheet += "\nQTableWidget { color: " + colors["accent"] + "; }"
        self.application.setStyleSheet(stylesheet)
        from . import app
        app.LIME, app.AMBER = colors["accent"], colors["secondary"]
        self.menu.header_texture = pixmap
        self.menu.skin_name = theme["name"]
        for widget in self.application.allWidgets():
            widget.update()
        if persist:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            output = QSaveFile(str(self.cache))
            if not output.open(QIODevice.WriteOnly):
                raise OSError("Theme applied for this session; could not save settings.")
            output.write(json.dumps(theme).encode("utf-8"))
            if not output.commit():
                raise OSError("Theme applied for this session; could not save settings.")

    def reset(self):
        self.apply({"name": "BitDeck", "palette": dict(palette.DEFAULT), "header_png": ""})
        self.cache.unlink(missing_ok=True)
