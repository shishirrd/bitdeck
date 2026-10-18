"""Cursor menu integration: native Qt drop events, desktop actions, bounded IPC.

This does not synthesize real Explorer/OLE gestures; that remains a separate
manual desktop check. It exercises the receiving widget's native event contract.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtNetwork import QLocalSocket

from bitdeck.app import create_application
from bitdeck.desktop import Desktop
from bitdeck.ipc import InstanceServer
from bitdeck.trigger import DragWatcher


def wait(application, predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(.01)
    assert predicate(), "Desktop integration action timed out"


def main():
    from reportlab.pdfgen.canvas import Canvas
    (ROOT / "work").mkdir(exist_ok=True)
    application = create_application()
    desktop = Desktop(application, single_instance=False)
    desktop.watcher.timer.stop()
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
            source = Path(folder) / "field-notes.pdf"
            canvas = Canvas(str(source))
            canvas.drawString(50, 700, "BitDeck cursor menu test")
            canvas.showPage()
            canvas.save()
            desktop.menu.popup(QPoint(400, 350), drag=True)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(source))])
            allowed = Qt.CopyAction | Qt.MoveAction
            enter = QDragEnterEvent(QPoint(300, 150), allowed, mime, Qt.LeftButton, Qt.ShiftModifier)
            desktop.menu.dragEnterEvent(enter)
            assert enter.isAccepted()
            assert enter.dropAction() == Qt.CopyAction
            assert desktop.menu.family == "pdf"
            assert [action.title for action in desktop.menu.actions] == ["PNG", "JPEG", "TXT"]
            # Drop on TXT sector (clockwise third sector at the upper-left).
            drop = QDropEvent(QPointF(135, 185), allowed, mime, Qt.LeftButton, Qt.NoModifier)
            desktop.menu.dropEvent(drop)
            assert drop.isAccepted() and drop.dropAction() == Qt.CopyAction
            wait(application, lambda: not desktop.runner.busy and bool(desktop.cards) and bool(desktop.cards[0].result))
            result = desktop.cards[0].result
            assert result["ok"], result
            assert "BitDeck cursor menu test" in Path(result["output"]).read_text(encoding="utf-8")
            assert source.exists()
            # Reject mixed-family and unsupported selections rather than silently
            # converting only a subset of the user's drop.
            text = Path(folder) / "notes.txt"
            text.write_text("Hello plain text\n", encoding="utf-8")
            mixed = QMimeData()
            mixed.setUrls([QUrl.fromLocalFile(str(source)), QUrl.fromLocalFile(str(text))])
            event = QDragEnterEvent(QPoint(300, 150), allowed, mixed, Qt.LeftButton, Qt.NoModifier)
            desktop.menu.dragEnterEvent(event)
            assert not event.isAccepted()
            desktop.show_files([str(text)])
            assert {action.key for action in desktop.menu.actions} == {"text_to_pdf", "text_normalize"}
            desktop.choose("text_to_pdf", [str(text)])
            wait(application, lambda: not desktop.runner.busy and desktop.cards[0].result.get("operation") == "text_to_pdf")
            assert Path(desktop.cards[0].result["output"]).suffix == ".pdf"
            # Named-pipe receiver accepts bounded structured file names only.
            server = InstanceServer(name="BitDeck-test-" + str(time.time_ns()))
            received = []
            if server.listening:
                server.requested.connect(lambda files, workbench: received.append((files, workbench)))
                client = QLocalSocket()
                client.connectToServer(server.server.serverName())
                assert client.waitForConnected(1000)
                client.write(json.dumps({"files": [str(text)], "workbench": False}).encode() + b"\n")
                client.flush()
                wait(application, lambda: bool(received))
                assert received == [([str(text)], False)]
            else:
                print("User-restricted IPC unavailable in this environment: " + server.server.errorString())
            server.close()
            # Polling state machine: Shift + moved left-button opens; a new Shift
            # press toggles; no normal character keys are queried.
            watcher = DragWatcher()
            pressed = set()
            queries = []
            class FakeUser:
                def GetAsyncKeyState(self, key):
                    queries.append(key)
                    return 0x8000 if key in pressed else 0
            watcher.user = FakeUser()
            opened, toggled = [], []
            watcher.activated.connect(opened.append)
            watcher.toggle.connect(lambda: toggled.append(True))
            with patch("bitdeck.trigger.QCursor.pos", return_value=QPoint(10, 10)):
                pressed.add(1)
                watcher.tick()
            with patch("bitdeck.trigger.QCursor.pos", return_value=QPoint(50, 10)):
                pressed.add(0x10)
                watcher.tick()
                pressed.remove(0x10)
                watcher.tick()
                pressed.add(0x10)
                watcher.tick()
            assert len(opened) == 1 and len(toggled) == 1
            assert set(queries) == {1, 0x10, 0x1B}
            if len(sys.argv) > 1:
                desktop.menu.popup(QPoint(400, 350), [str(source)], drag=False)
                desktop.menu.toggle()
                desktop.menu.hover = 1
                application.processEvents()
                desktop.menu.grab().save(sys.argv[1])
            print("Cursor integration passed: copy-only PDF drop -> TXT; text -> PDF; mixed drop rejection; drag/Shift polling. IPC verified: " + str(bool(received)))
    finally:
        desktop.shutdown()
        desktop.menu.deleteLater()
        for card in desktop.cards:
            card.deleteLater()
        desktop.tray.deleteLater()
        desktop.deleteLater()
        application.sendPostedEvents(None, QEvent.DeferredDelete)
        application.processEvents()


if __name__ == "__main__":
    main()
