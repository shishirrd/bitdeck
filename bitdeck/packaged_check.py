"""Headless checks of the packaged UI -> packaged worker path, no installed Python."""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import zipfile
import zlib

from PySide6.QtCore import QCoreApplication, QEvent
from .runner import WorkerRunner


def png_bytes():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 24, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\xb0\x60\x30" * 32) * 24)) + chunk(b"IEND", b"")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from .app import create_application
    application = create_application()
    application.setQuitOnLastWindowClosed(False)
    records = []

    def run(request):
        runner = WorkerRunner()
        result = []
        runner.completed.connect(result.append)
        runner.start(request)
        deadline = time.monotonic() + 90
        while not result and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.02)
        if not result:
            runner.shutdown()
            raise RuntimeError("Packaged worker timed out")
        runner.shutdown()
        runner.deleteLater()
        application.sendPostedEvents(None, QEvent.DeferredDelete)
        if not result[0].get("ok"):
            raise RuntimeError(result[0].get("error", "Packaged operation failed"))
        records.append({"operation": request["operation"], "ok": True})
        return result[0]

    try:
        with tempfile.TemporaryDirectory(prefix="bitdeck-check-") as folder:
            root = Path(folder)
            image = root / "image.png"
            image.write_bytes(png_bytes())
            preview = run({"operation": "inspect", "source": str(image)})
            assert (preview["width"], preview["height"]) == (32, 24)
            exported = run({"operation": "export", "source": str(image), "format": "WEBP", "output_dir": str(root / "out")})
            assert Path(exported["output"]).read_bytes()[:4] == b"RIFF"
            text = root / "notes.txt"
            text.write_text("BitDeck bundled PDF and text check\n", encoding="utf-8")
            pdf = run({"operation": "text_to_pdf", "source": str(text)})["output"]
            assert Path(pdf).read_bytes().startswith(b"%PDF-")
            run({"operation": "pdf_to_png", "source": pdf, "dpi": 72})
            extracted = run({"operation": "pdf_to_text", "source": pdf})
            assert "BitDeck bundled PDF" in Path(extracted["output"]).read_text(encoding="utf-8")
            merged = run({"operation": "pdf_merge", "source": pdf, "sources": [pdf, pdf]})
            split = run({"operation": "pdf_split", "source": merged["output"]})
            assert len(split["outputs"]) == 2
            protected = run({"operation": "pdf_protect", "source": pdf, "password": "packaged-test-password"})
            info = run({"operation": "pdf_inspect", "source": protected["output"], "input_password": "packaged-test-password"})
            assert info["pages"] == 1
            run({"operation": "pdf_preview", "source": protected["output"], "input_password": "packaged-test-password", "page": 0})
            run({"operation": "pdf_unlock", "source": protected["output"], "input_password": "packaged-test-password"})
            arranged = run({"operation": "pdf_organize", "source": merged["output"], "page_plan": [[0, 1, 90], [0, 0, 0]]})
            run({"operation": "pdf_split", "source": arranged["output"], "page_range": "2"})
            run({"operation": "pdf_edit_metadata", "source": pdf, "metadata": {"/Title": "Packaged controls"}})
            edited = run({"operation": "export", "source": str(image), "output_dir": str(root / "out"),
                "crop": [0, 0, .5, 1], "rotation": 90, "flip_horizontal": True,
                "annotations": [{"kind": "arrow", "box": [.1, .1, .4, .4], "color": "#ffcc00", "width": 2}]})
            assert (edited["width"], edited["height"]) == (24, 16)
            # Import and construct the new controls in the real frozen GUI.
            from .batch import BatchWindow
            from .pdf_ui import PDFWindow
            from .app import MainWindow
            batch = BatchWindow()
            controls = PDFWindow(batch)
            editor = MainWindow()
            editor.show_tools()
            editor.tools.hide()
            editor.closing = True
            editor.close()
            controls.close()
            batch.close()
            editor.deleteLater()
            controls.deleteLater()
            batch.deleteLater()
            application.sendPostedEvents(None, QEvent.DeferredDelete)
            application.processEvents()
            records.append({"operation": "editing_controls_construct", "ok": True})
            # A simple uncompressed 24-bit BMP in a real .wsz, generated using
            # standard Python only: verifies skin parsing dependencies in the worker.
            width, height = 275, 116
            row = bytes((88, 47, 28)) * width
            row += b"\0" * ((4 - len(row) % 4) % 4)
            pixels = row * height
            bmp = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0) + pixels
            skin = root / "Voltage Blue test.wsz"
            with zipfile.ZipFile(skin, "w") as archive:
                archive.writestr("MAIN.BMP", bmp)
                archive.writestr("PLEDIT.TXT", "[Text]\nNormal=#4dd0ff\nNormalBG=#080c14\n")
            theme = run({"operation": "import_theme", "source": str(skin)})
            assert theme["theme"]["palette"]["accent"] == "#4dd0ff"
            from .radial import CursorMenu
            from .theming import ThemeManager
            from .palette import ACTIVE, DEFAULT
            from PySide6.QtCore import QPoint
            menu = CursorMenu()
            manager = ThemeManager(application, menu, root / "theme-cache.json")
            manager.apply(theme["theme"], persist=True)
            assert ACTIVE["accent"] == "#4dd0ff" and not menu.header_texture.isNull()
            menu.popup(QPoint(400, 350), [pdf], drag=False)
            menu.toggle()
            menu.hover = 1
            application.processEvents()
            menu.grab().save(str(Path(args.report).with_suffix(".png")))
            manager.reset()
            assert ACTIVE == DEFAULT and "#4dd0ff" not in application.styleSheet()
            menu.hide()
            menu.deleteLater()
            application.sendPostedEvents(None, QEvent.DeferredDelete)
            application.processEvents()
            records.append({"operation": "skin_apply_and_reset", "ok": True})
        report = {"ok": True, "frozen": bool(getattr(sys, "frozen", False)), "checks": records}
    except Exception as error:
        report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": records, "error": str(error)}
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
