"""Winamp-inspired cursor menu. Native Qt drag/drop, not a file-selection proxy."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from .actions import actions_for, category
from .palette import color


class CursorMenu(QWidget):
    actionChosen = Signal(str, list)
    browseRequested = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(520, 500)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("BitDeck file actions. All actions are visible. Tab and arrow keys choose an action; Enter applies it. Escape closes.")
        self.paths = []
        self.family = None
        self.tools = False
        self.hover = -1
        self.drag_mode = True
        self.actions = []
        self.header_texture = QPixmap()
        self.skin_name = "BitDeck"

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
        self.actions = []
        seen = set()
        for action in actions_for(self.family, False) + actions_for(self.family, True):
            if action.key not in seen:
                self.actions.append(action)
                seen.add(action.key)
        self.setAccessibleDescription("; ".join(action.title + ": " + action.hint for action in self.actions))
        self.update()

    def toggle(self):
        # Compatibility for old callers: actions stay visible across Shift taps.
        pass

    def action_rect(self, index):
        columns = 3 if len(self.actions) > 4 else 2
        width = (488 - (columns - 1) * 8) / columns
        return QRectF(16 + (index % columns) * (width + 8),
                      86 + (index // columns) * 78, width, 70)

    def index_at(self, position):
        return next((index for index in range(len(self.actions))
                     if self.action_rect(index).contains(position)), -1)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(color("panel")))
        if not self.header_texture.isNull():
            painter.drawPixmap(self.rect().adjusted(1, 1, -1, -(self.height() - 40)), self.header_texture)
            painter.fillRect(QRectF(10, 8, 458, 25), QColor(color("display")))
        painter.setPen(QPen(QColor(color("border")), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setFont(QFont("Consolas", 12, QFont.Bold))
        painter.setPen(QColor(color("accent") if not self.header_texture.isNull() else color("text")))
        painter.drawText(QRectF(18, 9, 450, 25), Qt.AlignLeft, "B I T D E C K   /   DROP CONTROL")
        painter.setPen(QColor(color("muted")))
        painter.drawText(QRectF(477, 9, 28, 25), Qt.AlignCenter, "×")
        painter.fillRect(QRectF(16, 42, 488, 30), QColor(color("display")))
        painter.setPen(QColor(color("accent")))
        text = " / ".join([self.family.upper() if self.family else "WAITING FOR FILE", "ALL ACTIONS"])
        painter.drawText(QRectF(24, 42, 475, 30), Qt.AlignVCenter, text)
        if self.actions:
            for index, action in enumerate(self.actions):
                rect = self.action_rect(index)
                selected = index == self.hover
                painter.fillRect(rect, QColor(color("accent") if selected else color("control")))
                painter.setPen(QPen(QColor(color("text") if selected else color("border")), 1))
                painter.drawRect(rect)
                foreground = ("#101010" if QColor(color("accent")).lightness() > 130 else "#ffffff") if selected else color("text")
                painter.setPen(QColor(foreground))
                painter.setFont(QFont("Consolas", 10, QFont.Bold))
                painter.drawText(rect.adjusted(8, 3, -8, -39), Qt.AlignCenter, action.title)
                painter.setFont(QFont("Segoe UI", 9))
                summaries = {"pdf_controls": "Preview & arrange pages", "pdf_compress": "Lossless compression",
                    "pdf_split": "One PDF per page", "pdf_rotate": "Rotate PDF pages", "pdf_merge": "Combine PDF files",
                    "pdf_protect": "Set a PDF password", "pdf_extract": "Extract embedded images",
                    "pdf_metadata": "Remove document metadata", "pdf_to_text": "Extract text layer",
                    "pdf_to_png": "Export pages as PNG", "pdf_to_jpeg": "Export pages as JPEG",
                    "image_controls": "Crop, mark & edit metadata"}
                painter.drawText(rect.adjusted(8, 29, -8, -3), Qt.AlignCenter | Qt.TextWordWrap, summaries.get(action.key, action.hint))
            painter.fillRect(QRectF(16, 406, 488, 28), QColor(color("display")))
            painter.setPen(QColor(color("secondary")))
            painter.setFont(QFont("Consolas", 9))
            painter.drawText(QRectF(20, 406, 480, 28), Qt.AlignCenter,
                             "DROP HERE TO CHOOSE AFTER RELEASING" if self.drag_mode else f"{len(self.paths)} FILE(S) / CLICK AN ACTION")
        else:
            painter.setPen(QColor(color("accent")))
            painter.setFont(QFont("Consolas", 18))
            painter.drawText(QRectF(35, 150, 450, 120), Qt.AlignCenter | Qt.TextWordWrap,
                             "DRAG A FILE\nINTO THE MENU" if self.drag_mode else "DROP A FILE\nOR CLICK TO BROWSE")
            painter.setFont(QFont("Consolas", 11))
            painter.setPen(QColor(color("muted")))
            painter.drawText(QRectF(35, 290, 450, 40), Qt.AlignCenter, "IMAGES  /  PDF  /  TEXT")
        hint = self.actions[self.hover].hint if 0 <= self.hover < len(self.actions) else "All actions are visible. Drop on a button, or release below to choose afterward."
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(color("text")))
        painter.drawText(QRectF(20, 438, 480, 32), Qt.AlignCenter | Qt.TextWordWrap, hint)
        painter.setFont(QFont("Consolas", 9))
        painter.setPen(QColor(color("muted")))
        painter.drawText(QRectF(20, 475, 480, 18), Qt.AlignCenter, f"{self.skin_name[:24].upper()}  /  LOCAL FILES  /  ESC TO CLOSE")

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
            # Dropping outside the action buttons leaves a stable click menu.
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.drag_mode = False
            self.activateWindow()
            self.setFocus()
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key_Tab and self.actions:
            self.hover = (self.hover + (-1 if event.modifiers() & Qt.ShiftModifier else 1)) % len(self.actions)
            self.update()
        elif event.key() in {Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up} and self.actions:
            self.hover = (self.hover + (1 if event.key() in {Qt.Key_Right, Qt.Key_Down} else -1)) % len(self.actions)
            self.update()
        elif event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.hover >= 0:
            self.choose(self.hover)
