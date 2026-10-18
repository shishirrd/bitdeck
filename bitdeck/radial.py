"""Winamp-inspired cursor menu. Native Qt drag/drop, not a file-selection proxy."""
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .actions import Action, actions_for, category


class CursorMenu(QWidget):
    actionChosen = Signal(str, list)
    browseRequested = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(520, 500)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("BitDeck file actions. Tab switches Convert and Tools. Arrow keys choose an action; Enter applies it. Escape closes.")
        self.paths = []
        self.family = None
        self.tools = False
        self.hover = -1
        self.drag_mode = True
        self.actions = []

    def popup(self, position=None, paths=None, drag=True):
        self.paths = paths or []
        self.family = category(self.paths[0]) if self.paths else None
        self.tools = False
        self.hover = -1
        self.drag_mode = drag
        self.refresh()
        point = position or QCursor.pos()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(bounds.right() - self.width() + 1, point.x() - self.width() // 2))
        y = max(bounds.top(), min(bounds.bottom() - self.height() + 1, point.y() - self.height() // 2))
        self.move(x, y)
        self.show()
        self.raise_()
        if not drag:
            self.activateWindow()
            self.setFocus()

    def refresh(self):
        self.actions = actions_for(self.family, self.tools)
        self.setAccessibleDescription("; ".join(action.title + ": " + action.hint for action in self.actions))
        self.update()

    def toggle(self):
        if self.isVisible():
            self.tools = not self.tools
            self.hover = -1
            self.refresh()

    def index_at(self, position):
        delta = position - QPointF(260, 252)
        distance = math.hypot(delta.x(), delta.y())
        if not 76 <= distance <= 174 or not self.actions:
            return -1
        angle = (math.degrees(math.atan2(delta.y(), delta.x())) + 90) % 360
        return min(len(self.actions) - 1, int(angle / (360 / len(self.actions))))

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252930"))
        painter.setPen(QPen(QColor("#6b737e"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setFont(QFont("Consolas", 12, QFont.Bold))
        painter.setPen(QColor("#dce1d6"))
        painter.drawText(QRectF(18, 9, 450, 25), Qt.AlignLeft, "B I T D E C K   /   DROP CONTROL")
        painter.setPen(QColor("#959fa9"))
        painter.drawText(QRectF(477, 9, 28, 25), Qt.AlignCenter, "×")
        painter.fillRect(QRectF(16, 42, 488, 30), QColor("#10160f"))
        painter.setPen(QColor("#c4ee70"))
        text = " / ".join([self.family.upper() if self.family else "WAITING FOR FILE", "TOOLS" if self.tools else "CONVERT"])
        painter.drawText(QRectF(24, 42, 475, 30), Qt.AlignVCenter, text)
        if self.actions:
            count = len(self.actions)
            center = QPointF(260, 252)
            outer = QRectF(86, 78, 348, 348)
            inner = QRectF(184, 176, 152, 152)
            for index, action in enumerate(self.actions):
                # Clockwise sectors from noon; leave small gaps between tactile keys.
                start = 90 - index * 360 / count
                span = 360 / count
                path = QPainterPath()
                path.arcMoveTo(outer, start - 1)
                path.arcTo(outer, start - 1, -(span - 2))
                end_radians = math.radians(start - span + 1)
                path.lineTo(center + QPointF(76 * math.cos(end_radians), -76 * math.sin(end_radians)))
                path.arcTo(inner, start - span + 1, span - 2)
                path.closeSubpath()
                selected = index == self.hover
                painter.fillPath(path, QColor("#c4ee70" if selected else "#363d46"))
                painter.setPen(QPen(QColor("#efffd1" if selected else "#707987"), 1))
                painter.drawPath(path)
                mid = math.radians(start - span / 2)
                point = center + QPointF(132 * math.cos(mid), -132 * math.sin(mid))
                painter.setFont(QFont("Consolas", 11, QFont.Bold))
                painter.setPen(QColor("#14200d" if selected else "#e1e4dd"))
                painter.drawText(QRectF(point.x() - 62, point.y() - 25, 124, 50), Qt.AlignCenter | Qt.TextWordWrap, action.title)
            painter.setPen(QColor("#e8b768"))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(QRectF(187, 210, 146, 80), Qt.AlignCenter | Qt.TextWordWrap,
                             f"{len(self.paths)} FILE{'S' if len(self.paths) != 1 else ''}\n\nDROP ON ACTION" if self.drag_mode else "CHOOSE\nAN ACTION")
        else:
            painter.setPen(QColor("#c4ee70"))
            painter.setFont(QFont("Consolas", 18))
            painter.drawText(QRectF(35, 150, 450, 120), Qt.AlignCenter | Qt.TextWordWrap,
                             "DRAG A FILE\nINTO THE MENU" if self.drag_mode else "DROP A FILE\nOR CLICK TO BROWSE")
            painter.setFont(QFont("Consolas", 11))
            painter.setPen(QColor("#a1abb4"))
            painter.drawText(QRectF(35, 290, 450, 40), Qt.AlignCenter, "IMAGES  /  PDF  /  TEXT")
        hint = self.actions[self.hover].hint if 0 <= self.hover < len(self.actions) else "Tap Shift / Tab to switch Convert and Tools"
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor("#c2c7c9"))
        painter.drawText(QRectF(20, 438, 480, 32), Qt.AlignCenter | Qt.TextWordWrap, hint)
        painter.setFont(QFont("Consolas", 9))
        painter.setPen(QColor("#919ba4"))
        painter.drawText(QRectF(20, 475, 480, 18), Qt.AlignCenter, "ORIGINAL KEPT  /  LOCAL PROCESSING  /  ESC TO CLOSE")

    def mouseMoveEvent(self, event):
        self.hover = self.index_at(event.position())
        self.update()

    def mousePressEvent(self, event):
        if event.position().x() > 475 and event.position().y() < 40:
            self.hide()
        elif not self.drag_mode:
            index = self.index_at(event.position())
            if index >= 0:
                self.choose(index)
            elif not self.paths:
                self.browseRequested.emit()

    def choose(self, index):
        if 0 <= index < len(self.actions):
            action, paths = self.actions[index], list(self.paths)
            self.hide()
            self.actionChosen.emit(action.key, paths)

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        supported = [path for path in paths if category(path)]
        if supported:
            # Names only; no input parsing before drop, and mixed families are refused.
            families = {category(path) for path in paths}
            if len(families) != 1 or None in families:
                event.ignore()
                return
            self.paths, self.family = paths[:50], category(paths[0])
            self.refresh()
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event):
        self.hover = self.index_at(event.position())
        self.update()
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dropEvent(self, event):
        # Re-read the actual drop payload rather than trusting an earlier dragEnter.
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths or len(paths) > 50 or any(category(path) != self.family for path in paths):
            event.ignore()
            return
        self.paths = paths
        index = self.index_at(event.position())
        if index >= 0:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.choose(index)
        else:
            # Dropping in the hub changes to click mode, so the user can choose next.
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.drag_mode = False
            self.activateWindow()
            self.setFocus()
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif event.key() in {Qt.Key_Tab, Qt.Key_Shift}:
            self.toggle()
        elif event.key() in {Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up} and self.actions:
            self.hover = (self.hover + (1 if event.key() in {Qt.Key_Right, Qt.Key_Down} else -1)) % len(self.actions)
            self.update()
        elif event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.hover >= 0:
            self.choose(self.hover)
