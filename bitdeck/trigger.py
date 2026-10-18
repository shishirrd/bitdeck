"""Windows drag gesture detection. Polls only left mouse, Shift and Escape."""
import ctypes
import sys
from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor


class DragWatcher(QObject):
    activated = Signal(object)
    toggle = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self.origin = None
        self.shift_was = False
        self.fired = False
        self.timer = QTimer(self, interval=20)
        self.timer.timeout.connect(self.tick)
        self.user = ctypes.windll.user32 if sys.platform == "win32" else None

    def start(self):
        if self.user:
            self.timer.start()

    def tick(self):
        left, shift, escape = [bool(self.user.GetAsyncKeyState(key) & 0x8000) for key in (1, 0x10, 0x1B)]
        position = QCursor.pos()
        if escape:
            self.cancelled.emit()
        if not left:
            if self.fired:
                QTimer.singleShot(180, self.cancelled.emit)
            self.origin = None
            self.fired = False
        else:
            if self.origin is None:
                self.origin = position
            moved = (position - self.origin).manhattanLength() >= 10
            if self.enabled and moved and shift and not self.fired:
                self.fired = True
                self.activated.emit(position)
            elif self.enabled and self.fired and shift and not self.shift_was:
                self.toggle.emit()
        self.shift_was = shift
