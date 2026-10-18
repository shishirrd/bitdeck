"""Exercise actual UI actions and worker processes; optionally save a screenshot."""
import os
from pathlib import Path
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QFile, QEvent, Qt
from PySide6.QtWidgets import QMessageBox

from bitdeck.app import MainWindow, create_application


def wait(app, predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "UI action timed out"


def make_sample(path):
    """Original geometric test image; no external assets."""
    image = Image.new("RGB", (1440, 900), "#151f2d")
    draw = ImageDraw.Draw(image)
    for y in range(900):
        ratio = y / 900
        draw.line((0, y, 1440, y), fill=(int(20 + ratio * 35), int(31 + ratio * 18), int(46 + ratio * 32)))
    draw.ellipse((850, 100, 1210, 460), fill="#e8b768")
    for y in range(170, 460, 26):
        draw.rectangle((840, y, 1220, y + 7), fill="#2c2b3e")
    draw.polygon([(0, 670), (260, 380), (510, 630), (750, 330), (1110, 730), (1440, 470), (1440, 900), (0, 900)], fill="#334d5b")
    draw.polygon([(0, 790), (430, 550), (710, 830), (1050, 520), (1440, 800), (1440, 900), (0, 900)], fill="#1b303c")
    draw.rectangle((80, 80, 490, 280), outline="#c4ee70", width=3)
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"
    font = ImageFont.truetype(str(font_path), 42) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 25) if font_path.exists() else ImageFont.load_default()
    draw.text((110, 112), "SIGNAL STUDY", fill="#c4ee70", font=font)
    draw.text((112, 187), "ORIGINAL TEST IMAGE\n1440 x 900 / RGB", fill="#b8c4cb", font=small, spacing=10)
    image.save(path)


def main():
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as directory:
        source = Path(directory) / "signal-study.png"
        make_sample(source)
        application = create_application()
        window = MainWindow()
        window.show()
        try:
            window.add_files([str(source)])
            wait(application, lambda: not window.canvas.pixmap.isNull())
            assert window.export_button.isEnabled()
            window.long_edge.setValue(1200)
            window.quality.setValue(82)
            window.export_button.click()
            wait(application, lambda: window.items[0].state in {"DONE", "FAILED"})
            assert window.items[0].state == "DONE", window.items[0].detail
            result = window.items[0].result
            output = Path(result["output"])
            assert output.exists()
            assert result["width"] == 1200
            # UI marks and exports an opaque redaction, preserving the first output.
            window.format.setCurrentText("PNG")
            window.canvas.boxes.append([.07, .12, .3, .23])
            window.boxes_changed()
            window.export_button.click()
            wait(application, lambda: window.items[0].state in {"DONE", "FAILED"})
            assert window.items[0].state == "DONE", window.items[0].detail
            redacted = Path(window.items[0].result["output"])
            with Image.open(redacted) as image:
                assert image.getpixel((150, 120)) == (0, 0, 0)
            assert output.exists()
            # Fail trash on purpose; the file MUST remain. Avoid interacting with
            # the user's actual Recycle Bin.
            question, trash = QMessageBox.question, QFile.moveToTrash
            QMessageBox.question = lambda *_args, **_kwargs: QMessageBox.Yes
            QFile.moveToTrash = lambda *_args: False
            try:
                window.undo_button.click()
                assert redacted.exists()
                assert "nothing permanently deleted" in window.status.text()
            finally:
                QMessageBox.question, QFile.moveToTrash = question, trash
            # An externally changed output must be refused before trash is called.
            redacted.write_bytes(b"replaced output")
            QMessageBox.question = lambda *_args, **_kwargs: QMessageBox.Yes
            try:
                window.undo_button.click()
                assert redacted.read_bytes() == b"replaced output"
                assert "Undo refused" in window.status.text()
            finally:
                QMessageBox.question = question
            if len(sys.argv) > 1:
                window.status.setText("SAVED  /  Preview and export verified. Original file kept.")
                application.processEvents()
                window.grab().save(sys.argv[1])
            print("UI integration passed: preview, WebP export, resize, PNG redaction, safe Undo failure, changed-file refusal.")
        finally:
            window.closing = True
            window.close()
            application.processEvents()
            # Deterministic ownership order: destroy widgets and pending child
            # process QObjects before QApplication and its font engine.
            window.deleteLater()
            application.sendPostedEvents(None, QEvent.DeferredDelete)
            application.processEvents()


if __name__ == "__main__":
    main()
