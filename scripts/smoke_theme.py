"""Import .wsz through a real worker; apply, persist, reload and reset in Qt."""
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint
from bitdeck.app import create_application
from bitdeck.palette import ACTIVE, DEFAULT
from bitdeck.radial import CursorMenu
from bitdeck.runner import WorkerRunner
from bitdeck.theming import ThemeManager


def main():
    import io
    import zipfile
    from PIL import Image, ImageDraw
    application = create_application()
    menu = CursorMenu()
    (ROOT / "work").mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
            root = Path(folder)
            skin = root / "Voltage Blue.wsz"
            bitmap = Image.new("RGB", (275, 116), (28, 47, 88))
            draw = ImageDraw.Draw(bitmap)
            draw.rectangle((0, 0, 274, 13), fill="#384f84")
            for x in range(4, 275, 8):
                draw.line((x, 1, x, 12), fill="#7292ce")
            encoded = io.BytesIO()
            bitmap.save(encoded, "BMP")
            with zipfile.ZipFile(skin, "w") as archive:
                archive.writestr("MAIN.BMP", encoded.getvalue())
                archive.writestr("PLEDIT.TXT", "[Text]\nNormal=#4dd0ff\nNormalBG=#080c14\nCurrent=#ffe38a\n")
            runner = WorkerRunner()
            results = []
            runner.completed.connect(results.append)
            runner.start({"operation": "import_theme", "source": str(skin)})
            deadline = time.monotonic() + 15
            while not results and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(.01)
            assert results and results[0]["ok"], results
            cache = root / "theme.json"
            manager = ThemeManager(application, menu, cache)
            manager.apply(results[0]["theme"], persist=True)
            assert cache.is_file()
            assert ACTIVE["accent"] == "#4dd0ff"
            assert not menu.header_texture.isNull()
            manager2 = ThemeManager(application, menu, cache)
            assert manager2.current["name"] == "Voltage Blue"
            manager2.reset()
            assert ACTIVE == DEFAULT and not cache.exists()
            assert menu.header_texture.isNull()
            assert "#4dd0ff" not in application.styleSheet()
            assert "#c4ee70" in application.styleSheet()
            manager.apply(results[0]["theme"])
            menu.popup(QPoint(400, 350), ["example.pdf"], drag=False)
            menu.toggle()
            menu.hover = 1
            application.processEvents()
            if len(sys.argv) > 1:
                menu.grab().save(sys.argv[1])
            runner.shutdown()
            runner.deleteLater()
            print("Theme integration passed: worker .wsz import, bitmap/color application, cache reload and default reset.")
    finally:
        menu.hide()
        menu.deleteLater()
        application.sendPostedEvents(None, QEvent.DeferredDelete)
        application.processEvents()


if __name__ == "__main__":
    main()
