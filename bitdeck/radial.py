"""Animated radial drop menu. Geometry stays fixed throughout each gesture."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QVariantAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QLinearGradient
from PySide6.QtWidgets import QApplication, QWidget
from .actions import actions_for, category
from .palette import color
from .motion import motion_enabled


def blend(first, second, amount):
    a, b = QColor(first), QColor(second)
    return QColor(*(round(x + (y - x) * amount) for x, y in zip(a.getRgb(), b.getRgb())))


class CursorMenu(QWidget):
    actionChosen = Signal(str, list)
    browseRequested = Signal()
    CENTER = QPointF(280, 286)
    INNER, OUTER = 88, 204

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(560, 580)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("BitDeck radial file actions. All actions are visible. Drop in the center to choose after releasing. Tab or arrows select; Enter applies; Escape closes.")
        self.paths, self.actions = [], []
        self.family = None
        self.hover = -1
        self.drag_mode = True
        self.header_texture = QPixmap()
        self.skin_name = "BitDeck"
        self._weights, self._starts = [], []
        self._reveal = 1.0
        self._committing = self._closing = False
        self._pending = None
        self._pressed = None
        self._polygons = []
        self._shadow = QPixmap()
        self.reveal_animation = QVariantAnimation(self)
        self.reveal_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.reveal_animation.valueChanged.connect(self._reveal_frame)
        self.reveal_animation.finished.connect(self._reveal_finished)
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setDuration(140)
        self.hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.hover_animation.valueChanged.connect(self._hover_frame)
        self.dispatch_timer = QTimer(self, singleShot=True)
        self.dispatch_timer.timeout.connect(self._dispatch)

    def popup(self, position=None, paths=None, drag=True):
        if self._pending is not None:
            return
        self.reveal_animation.stop()
        self._closing = self._committing = False
        self._pressed = None
        self.paths = paths or []
        self.family = category(self.paths[0]) if self.paths else None
        self.hover = -1
        self.drag_mode = drag
        self.refresh()
        self.hover_animation.stop()
        self._weights = [0.0] * len(self.actions)
        point = position or QCursor.pos()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        factor = min(1.0, bounds.width() / 560, bounds.height() / 580)
        self.setFixedSize(round(560 * factor), round(580 * factor))
        x = max(bounds.left(), min(bounds.right() - self.width() + 1, round(point.x() - self.CENTER.x() * factor)))
        y = max(bounds.top(), min(bounds.bottom() - self.height() + 1, round(point.y() - self.CENTER.y() * factor)))
        self.move(x, y)
        self._reveal = 0.0 if motion_enabled() else 1.0
        self.show()
        self.raise_()
        self._fade(1.0, 160)
        if not drag:
            self.activateWindow()
            self.setFocus()

    def refresh(self):
        actions, seen = [], set()
        for action in actions_for(self.family, False) + actions_for(self.family, True):
            if action.key not in seen:
                actions.append(action)
                seen.add(action.key)
        if actions != self.actions:
            self.hover_animation.stop()
            self.hover = -1
            self._weights = [0.0] * len(actions)
            self.actions = actions
            self._polygons = [self.sector_path(i) for i in range(len(actions))]
            self._cache_shadow()
        self.setAccessibleDescription("; ".join(a.title + ": " + a.hint for a in self.actions))
        self.update()

    def toggle(self):
        pass  # Compatibility: all actions stay visible across old toggle calls.

    def logical(self, point):
        return QPointF(point.x() * 560 / self.width(), point.y() * 580 / self.height())

    def sector_path(self, index):
        span = 360 / len(self.actions)
        start = 90 - index * span
        outside, inside = self.OUTER - 6, self.INNER + 7
        outer = QRectF(self.CENTER.x() - outside, self.CENTER.y() - outside, outside * 2, outside * 2)
        inner = QRectF(self.CENTER.x() - inside, self.CENTER.y() - inside, inside * 2, inside * 2)
        path = QPainterPath()
        path.arcMoveTo(outer, start - 3.5)
        path.arcTo(outer, start - 3.5, -(span - 7))
        radians = math.radians(start - span + 3.5)
        path.lineTo(self.CENTER + QPointF(inside * math.cos(radians), -inside * math.sin(radians)))
        path.arcTo(inner, start - span + 3.5, span - 7)
        path.closeSubpath()
        rounding = QPainterPathStroker()
        rounding.setWidth(8)
        rounding.setJoinStyle(Qt.RoundJoin)
        rounding.setCapStyle(Qt.RoundCap)
        return path.united(rounding.createStroke(path)).simplified()

    def action_point(self, index):
        angle = math.radians(-90 + (index + .5) * 360 / len(self.actions))
        point = self.CENTER + QPointF(148 * math.cos(angle), 148 * math.sin(angle))
        return QPointF(point.x() * self.width() / 560, point.y() * self.height() / 580)

    def index_at(self, position, sticky=False):
        delta = self.logical(position) - self.CENTER
        radius = math.hypot(delta.x(), delta.y())
        if not self.INNER <= radius <= self.OUTER or not self.actions:
            return -1
        angle = (math.degrees(math.atan2(delta.y(), delta.x())) + 90) % 360
        span = 360 / len(self.actions)
        if sticky and self.hover >= 0:
            distance = abs((angle - (self.hover + .5) * span + 180) % 360 - 180)
            if distance <= span / 2 + 2.5:
                return self.hover
        return min(len(self.actions) - 1, int(angle / span))

    def set_hover(self, index):
        if self._closing or self._committing or index == self.hover:
            return
        self.hover_animation.stop()
        self._starts = list(self._weights)
        self.hover = index
        if motion_enabled():
            self.hover_animation.setStartValue(0.0)
            self.hover_animation.setEndValue(1.0)
            self.hover_animation.start()
        else:
            self._hover_frame(1.0)

    def _hover_frame(self, progress):
        self._weights = [value + ((1.0 if i == self.hover else 0.0) - value) * float(progress)
                         for i, value in enumerate(self._starts)]
        self.update()

    def _reveal_frame(self, value):
        self._reveal = float(value)
        self.update()

    def _fade(self, target, duration):
        self.reveal_animation.stop()
        if not motion_enabled():
            self._reveal_frame(target)
            if self._closing:
                self._reveal_finished()
            return
        self.reveal_animation.setDuration(duration)
        self.reveal_animation.setStartValue(self._reveal)
        self.reveal_animation.setEndValue(target)
        self.reveal_animation.start()

    def _reveal_finished(self):
        if self._closing:
            self.hide()
            if self._pending is not None:
                self.dispatch_timer.start(0)

    def _dispatch(self):
        pending, self._pending = self._pending, None
        self._committing = False
        if pending:
            self.actionChosen.emit(*pending)

    def cancel_pending(self):
        self.reveal_animation.stop()
        self.hover_animation.stop()
        self.dispatch_timer.stop()
        self._pending = None
        self._pressed = None
        self._committing = self._closing = False
        self.hide()

    def settle(self):
        """Finish presentation only, for deterministic screenshots/checks."""
        if not self._committing:
            self.reveal_animation.stop()
            self.hover_animation.stop()
            self._reveal = 1.0
            self._weights = [1.0 if i == self.hover else 0.0 for i in range(len(self.actions))]
            self.update()

    def _cache_shadow(self):
        self._shadow = QPixmap(560, 580)
        self._shadow.fill(Qt.transparent)
        painter = QPainter(self._shadow)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(0, 5)
        for path in self._polygons:
            for width in (20, 16, 12, 8, 4):
                painter.setPen(QPen(QColor(0, 0, 0, 10), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
            painter.fillPath(path, QColor(0, 0, 0, 45))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35))
        painter.drawEllipse(self.CENTER, self.INNER - 5, self.INNER - 5)
        painter.end()

    def _icon(self, painter, key, point):
        painter.save()
        painter.translate(point)
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if key == 'pdf_protect':
            painter.drawArc(QRectF(-4, -7, 8, 10), 0, 180 * 16)
            painter.drawRoundedRect(QRectF(-6, -2, 12, 10), 2, 2)
            painter.drawLine(QPointF(0, 2), QPointF(0, 4))
        elif key == 'pdf_rotate':
            painter.drawArc(QRectF(-6, -6, 12, 12), 30*16, 290*16)
            painter.drawLine(QPointF(5, -6), QPointF(5, -1))
            painter.drawLine(QPointF(5, -1), QPointF(1, -3))
        elif key in {'pdf_metadata', 'clean_image'}:
            painter.drawEllipse(QPointF(0, 0), 7, 7)
            painter.setFont(QFont('Segoe UI', 9, QFont.Bold))
            painter.drawText(QRectF(-7, -9, 14, 18), Qt.AlignCenter, 'i')
        elif key in {'pdf_split', 'pdf_merge', 'pdf_controls'}:
            painter.drawRoundedRect(QRectF(-8, -6, 6, 12), 1, 1)
            painter.drawRoundedRect(QRectF(2, -6, 6, 12), 1, 1)
            if key == 'pdf_merge':
                painter.drawLine(QPointF(-1, 0), QPointF(1, 0))
            elif key == 'pdf_split':
                painter.drawLine(QPointF(0, -7), QPointF(0, 7))
        elif key in {'pdf_extract', 'images_to_pdf'}:
            painter.drawRoundedRect(QRectF(-8, -6, 16, 12), 2, 2)
            painter.drawLine(QPointF(-6, 4), QPointF(-1, -1))
            painter.drawLine(QPointF(-1, -1), QPointF(4, 4))
            painter.drawEllipse(QPointF(4, -2), 1.5, 1.5)
        elif key in {'compress_image', 'pdf_compress', 'resize_image'}:
            painter.drawLine(QPointF(-6, -6), QPointF(6, 6))
            painter.drawLine(QPointF(-6, -1), QPointF(-6, -6))
            painter.drawLine(QPointF(-6, -6), QPointF(-1, -6))
            painter.drawLine(QPointF(1, 6), QPointF(6, 6))
            painter.drawLine(QPointF(6, 6), QPointF(6, 1))
        elif key in {'image_controls', 'workbench'}:
            painter.drawLine(QPointF(-5, 5), QPointF(5, -5))
            painter.drawLine(QPointF(-5, 5), QPointF(-6, 8))
            painter.drawLine(QPointF(-6, 8), QPointF(-3, 7))
            painter.drawLine(QPointF(3, -6), QPointF(6, -3))
        else:
            painter.drawRoundedRect(QRectF(-6, -8, 12, 16), 2, 2)
            painter.drawLine(QPointF(-3, -2), QPointF(3, -2))
            painter.drawLine(QPointF(-3, 2), QPointF(3, 2))
        painter.restore()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 560, self.height() / 580)
        painter.setOpacity(self._reveal)
        # Floating surfaces: desktop remains visible between the rounded wedges.
        painter.drawPixmap(0, 0, self._shadow)
        painter.setPen(QPen(blend(color('border'), '#ffffff', .15), 1))
        painter.setBrush(QColor(color('panel')))
        painter.drawRoundedRect(QRectF(115, 24, 330, 35), 17, 17)
        if not self.header_texture.isNull():
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(119, 27, 322, 29), 14, 14)
            painter.setClipPath(clip)
            painter.drawPixmap(QRectF(119, 27, 322, 29).toRect(), self.header_texture)
            painter.restore()
        painter.setPen(QColor(color('text')))
        painter.setFont(QFont('Consolas', 9, QFont.Bold))
        title = 'BITDECK  /  ' + (self.family.upper() if self.family else 'DROP A FILE')
        painter.drawText(QRectF(125, 24, 310, 35), Qt.AlignCenter, title)
        painter.setBrush(QColor(color('panel')))
        painter.setPen(QPen(QColor(color('border')), 1))
        painter.drawEllipse(QPointF(531, 26), 12, 12)
        painter.setPen(QColor(color('muted')))
        painter.setFont(QFont('Segoe UI', 10))
        painter.drawText(QRectF(519, 12, 24, 26), Qt.AlignCenter, '×')
        if self.actions:
            for index, (action, path) in enumerate(zip(self.actions, self._polygons)):
                weight = self._weights[index]
                bounds = path.boundingRect()
                top = blend(color('control'), '#ffffff', .15)
                bottom = blend(color('control'), '#000000', .035)
                top = blend(top, color('accent'), weight * .22)
                bottom = blend(bottom, color('accent'), weight * .12)
                gradient = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
                gradient.setColorAt(0, top)
                gradient.setColorAt(1, bottom)
                painter.setBrush(gradient)
                painter.setPen(QPen(blend(blend(color('border'), '#ffffff', .27), color('accent'), weight * .8), 1.2 + weight * .4))
                painter.drawPath(path)
                angle = math.radians(-90 + (index + .5) * 360 / len(self.actions))
                point = self.CENTER + QPointF(148 * math.cos(angle), 148 * math.sin(angle))
                painter.setPen(QColor(color('text')))
                self._icon(painter, action.key, point + QPointF(0, -19))
                painter.setFont(QFont('Segoe UI', 9, QFont.DemiBold))
                title = action.title.replace('Page controls', 'Page\ncontrols').replace('Clean info', 'Clean\ninfo').replace('Edit image', 'Edit\nimage').replace('Clean tags', 'Clean\ntags')
                painter.drawText(QRectF(point.x() - 36, point.y() - 4, 72, 37), Qt.AlignCenter | Qt.TextWordWrap, title)
            gradient = QLinearGradient(QPointF(280, 203), QPointF(280, 369))
            gradient.setColorAt(0, blend(color('panel'), '#ffffff', .10))
            gradient.setColorAt(1, QColor(color('panel')))
            painter.setBrush(gradient)
            painter.setPen(QPen(blend(color('border'), '#ffffff', .25), 1.3))
            painter.drawEllipse(self.CENTER, self.INNER - 8, self.INNER - 8)
            painter.setPen(QColor(color('text')))
            painter.setFont(QFont('Segoe UI', 11, QFont.DemiBold))
            text = self.actions[self.hover].title if self.hover >= 0 else f'{len(self.actions)} actions'
            painter.drawText(QRectF(213, 242, 134, 43), Qt.AlignCenter | Qt.TextWordWrap, text)
            painter.setPen(QColor(color('muted')))
            painter.setFont(QFont('Segoe UI', 9))
            text = ('Release to apply' if self.drag_mode else 'Click to apply') if self.hover >= 0 else ('Release here,\nthen choose' if self.drag_mode else 'Choose an action')
            painter.drawText(QRectF(214, 294, 132, 42), Qt.AlignCenter, text)
        else:
            painter.setPen(QColor(color('text')))
            painter.setBrush(QColor(color('panel')))
            painter.drawEllipse(self.CENTER, 120, 120)
            painter.setFont(QFont('Segoe UI', 15, QFont.DemiBold))
            painter.drawText(QRectF(180, 226, 200, 120), Qt.AlignCenter, 'Drag a file\ninto the wheel' if self.drag_mode else 'Click to browse')
        painter.setBrush(QColor(color('panel')))
        painter.setPen(QPen(QColor(color('border')), 1))
        painter.drawRoundedRect(QRectF(40, 507, 480, 57), 17, 17)
        hint = self.actions[self.hover].hint if 0 <= self.hover < len(self.actions) else 'Every action is on the wheel. Release in the center to choose afterward.'
        painter.setFont(QFont('Segoe UI', 9))
        painter.setPen(QColor(color('text')))
        painter.drawText(QRectF(55, 512, 450, 46), Qt.AlignCenter | Qt.TextWordWrap, hint)

    def mouseMoveEvent(self, event):
        self.set_hover(self.index_at(event.position(), sticky=True))

    def leaveEvent(self, event):
        self.set_hover(-1)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._closing or self._committing:
            return
        point = self.logical(event.position())
        if point.x() > 515 and point.y() < 40:
            self._pressed = "close"
        elif not self.drag_mode:
            index = self.index_at(event.position(), sticky=True)
            if index >= 0:
                self._pressed = index
                self.set_hover(index)
            elif not self.paths:
                self._pressed = "browse"

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, None
        if event.button() != Qt.LeftButton or self._closing or self._committing:
            return
        point = self.logical(event.position())
        if pressed == "close" and point.x() > 515 and point.y() < 40:
            self._closing = True
            self._fade(0.0, 90)
        elif type(pressed) is int and self.index_at(event.position(), sticky=True) == pressed:
            self.choose(pressed)
        elif pressed == "browse" and not self.paths:
            QTimer.singleShot(0, self.browseRequested.emit)

    def choose(self, index):
        if self.isVisible() and not self._closing and not self._committing and 0 <= index < len(self.actions):
            self._committing = self._closing = True
            self._pending = (self.actions[index].key, list(self.paths))
            self._fade(0.0, 95)

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        families = {category(path) for path in paths}
        if not self.isVisible() or self._closing or self._committing or not paths or len(paths) > 50 or len(families) != 1 or None in families:
            event.ignore()
            return
        self.paths, self.family = paths, category(paths[0])
        self.refresh()
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragMoveEvent(self, event):
        if self._committing:
            event.ignore()
            return
        self.set_hover(self.index_at(event.position(), sticky=True))
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not self.isVisible() or self._closing or self._committing or not paths or len(paths) > 50 or any(category(path) != self.family for path in paths):
            event.ignore()
            return
        self.paths = paths
        index = self.index_at(event.position(), sticky=True)
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if index >= 0:
            self.choose(index)
        else:
            self.drag_mode = False
            self.set_hover(-1)
            self.activateWindow()
            self.setFocus()
            self.update()

    def keyPressEvent(self, event):
        if self._closing or self._committing:
            return
        if event.key() == Qt.Key_Escape:
            self._closing = True
            self._fade(0.0, 90)
        elif event.key() in {Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up} and self.actions:
            backwards = event.key() in {Qt.Key_Backtab, Qt.Key_Left, Qt.Key_Up} or (event.key() == Qt.Key_Tab and event.modifiers() & Qt.ShiftModifier)
            index = (len(self.actions) - 1 if backwards else 0) if self.hover < 0 else (self.hover + (-1 if backwards else 1)) % len(self.actions)
            self.set_hover(index)
        elif event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.hover >= 0 and not self.drag_mode:
            self.choose(self.hover)
