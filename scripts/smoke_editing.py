"""Real Qt controls and isolated workers: editing, PDF assembly, partial failures."""
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from pypdf import PdfReader, PdfWriter
from PySide6.QtCore import Qt, QEvent
from bitdeck.app import create_application, MainWindow
from bitdeck.batch import BatchWindow
from bitdeck.pdf_ui import PDFWindow


def wait(app, predicate):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for Qt worker")


def main():
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    batch = BatchWindow()
    pdf = PDFWindow(batch)
    window = MainWindow()
    callback_errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, error, tb: callback_errors.append(str(error))
    try:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "image.png"
            Image.new("RGB", (120, 80), "white").save(image)
            window.add_files([str(image)])
            wait(app, lambda: bool(window.selected().fingerprint))
            window.show_tools()
            tools = window.tools
            tools.tool.setCurrentText("Crop")
            tools.selection([0, 0, .5, 1])
            tools.rotation.setCurrentText("90")
            tools.tool.setCurrentText("Arrow")
            tools.selection([.1, .1, .4, .4])
            window.queue_all()
            wait(app, lambda: window.items[0].state in {"DONE", "FAILED"})
            assert window.items[0].state == "DONE", window.items[0].detail
            assert (window.items[0].result["width"], window.items[0].result["height"]) == (80, 60)
            source = root / "pages.pdf"
            from reportlab.pdfgen.canvas import Canvas
            canvas = Canvas(str(source), pagesize=(100, 200))
            canvas.setFont("Helvetica", 9)
            canvas.drawString(8, 180, "BitDeck / cover")
            canvas.showPage()
            canvas.setPageSize((300, 400))
            canvas.setFillColorRGB(.1, .2, .3)
            canvas.rect(0, 300, 300, 100, fill=1, stroke=0)
            canvas.setFillColorRGB(1, 1, 1)
            canvas.setFont("Helvetica-Bold", 20)
            canvas.drawString(24, 345, "BITDECK")
            canvas.setFillColorRGB(.1, .2, .3)
            canvas.setFont("Helvetica", 12)
            canvas.drawString(24, 260, "Page controls / sample document")
            canvas.drawString(24, 230, "Preview. Arrange. Export a copy.")
            canvas.save()
            pdf.add_files([str(source)])
            wait(app, lambda: pdf.pages.count() == 2)
            pdf.pages.setCurrentRow(1)
            wait(app, lambda: not pdf.previewer.busy and pdf.preview.pixmap() is not None and not pdf.preview.pixmap().isNull())
            pdf.rotate()
            pdf.move(-1)
            pdf.organize()
            wait(app, lambda: bool(batch.records) and batch.records[-1]["state"] in {"DONE", "FAILED"})
            result = batch.records[-1]["result"]
            assert result["ok"], result
            output = PdfReader(result["output"])
            assert int(output.pages[0].mediabox.width) == 300
            assert output.pages[0].rotation == 90
            pdf.range.setText("2")
            pdf.export()
            wait(app, lambda: batch.records[-1]["state"] in {"DONE", "FAILED"})
            assert len(PdfReader(batch.records[-1]["result"]["output"]).pages) == 1
            batch.pause()
            requests = [dict(operation="export", source=str(root / "missing.png"), output_dir=str(root / "out")),
                        dict(operation="export", source=str(image), output_dir=str(root / "out"))]
            batch.submit(requests)
            requests[1]["source"] = "changed after queueing"
            assert batch.records[-1]["state"] == "QUEUED"
            batch.pause()
            wait(app, lambda: not batch.pending and not batch.runner.busy)
            assert [row["state"] for row in batch.records[-2:]] == ["FAILED", "DONE"]
            Image.new("RGB", (10, 10), "red").save(root / "missing.png")
            batch.retry()
            wait(app, lambda: not batch.pending and not batch.runner.busy)
            assert batch.records[-2]["state"] == "DONE"
            batch.pause()
            batch.submit([dict(operation="export", source=str(image))])
            batch.cancel_all()
            assert batch.records[-1]["state"] == "CANCELLED"
            if len(sys.argv) > 1:
                wait(app, lambda: not pdf.previewer.busy and pdf.pending_preview is None)
                pdf.show()
                app.processEvents()
                pdf.grab().save(sys.argv[1])
            print("Editing UI passed: crop/rotate/annotation, PDF preview/arrange/range, queue pause/cancel/retry/partial failure.")
    finally:
        window.closing = True
        window.runner.shutdown()
        window.inspector.shutdown()
        if window.tools:
            window.tools.preview_runner.shutdown()
        pdf.inspector.shutdown()
        pdf.previewer.shutdown()
        batch.runner.shutdown()
        window.close()
        pdf.close()
        batch.close()
        window.deleteLater()
        pdf.deleteLater()
        batch.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        sys.excepthook = previous_hook
    assert not callback_errors, callback_errors


if __name__ == "__main__":
    main()
