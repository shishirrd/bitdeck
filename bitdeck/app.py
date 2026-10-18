from __future__ import annotations

import argparse
import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
import sys

from PySide6.QtCore import QFile, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView)

from .runner import WorkerRunner

LIME = "#c4ee70"
AMBER = "#e8b768"

STYLE = """
QWidget { background: #22252b; color: #deded9; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow { background: #17191e; }
QFrame#panel { background: #282c33; border: 1px solid #454a52; border-bottom-color: #111318; border-right-color: #111318; }
QLabel { background: transparent; border: none; }
QLabel#dim { color: #92989f; }
QLabel#section { color: #b7bdc5; font-family: Consolas; font-size: 11px; letter-spacing: 2px; }
QLabel#display { color: #c4ee70; font-family: Consolas; font-size: 20px; background: #101610; padding: 10px; border: 1px solid #080b08; }
QPushButton { background: #3b4048; border: 1px solid #626975; border-right-color: #13161b; border-bottom-color: #13161b; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #484f58; border-top-color: #a2aaae; }
QPushButton:pressed, QPushButton:checked { background: #1b2220; border: 1px solid #c4ee70; color: #c4ee70; }
QPushButton:disabled { color: #777d85; background: #2d3138; border-color: #373c43; }
QPushButton#primary { color: #151c10; background: #c4ee70; border-top-color: #e8ffb0; border-left-color: #e8ffb0; border-right-color: #556b2d; border-bottom-color: #556b2d; }
QPushButton#primary:hover { background: #d7ff87; }
QPushButton#primary:disabled { background: #424c36; color: #8b977b; border-color: #424c36; }
QComboBox, QSpinBox { background: #14181d; border: 1px solid #535963; padding: 7px; color: #e8b768; font-family: Consolas; }
QComboBox QAbstractItemView { background: #20252a; color: #e8b768; selection-background-color: #3b4540; }
QSlider::groove:horizontal { background: #111518; height: 6px; border: 1px solid #080b0e; }
QSlider::sub-page:horizontal { background: #a2ba70; }
QSlider::handle:horizontal { background: #b6bdc5; border: 1px solid #f0f2e8; width: 12px; margin: -5px 0; border-bottom: 3px solid #626971; }
QTableWidget { background: #13181b; alternate-background-color: #171c1f; border: 1px solid #080d10; gridline-color: #2c3338; selection-background-color: #303c32; font-family: Consolas; }
QTableWidget::item { padding: 7px; background: transparent; }
QHeaderView::section { background: #30353c; color: #a9b0b6; border: none; border-right: 1px solid #15191d; padding: 7px; font-size: 10px; font-family: Consolas; }
QProgressBar { background: #0c110e; border: 1px solid #060907; height: 5px; color: transparent; }
QProgressBar::chunk { background: #c4ee70; width: 12px; margin: 1px; }
QSplitter::handle { background: #17191e; }
QToolTip { background: #13181b; color: #deded9; border: 1px solid #626975; padding: 6px; }
QScrollBar:vertical { background: #171c20; width: 10px; }
QScrollBar::handle:vertical { background: #555e67; min-height: 20px; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, tooltip, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    widget.setToolTip(tooltip)
    widget.setAccessibleName(text)
    if primary:
        widget.setObjectName("primary")
    return widget


def panel(title):
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(12)
    layout.addWidget(label(title, "section"))
    return widget, layout


def human_bytes(count):
    return f"{count / 1024 / 1024:.2f} MiB" if count >= 1024 * 1024 else f"{count / 1024:.1f} KiB"


class Spectrum(QWidget):
    """A discrete phase display, not an invented percent-complete meter."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(92, 29)
        self.active = False
        self.setAccessibleName("Worker activity indicator")

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101610"))
        for column, height in enumerate([2, 4, 3, 6, 5, 3, 4, 7, 5, 3, 2, 4]):
            for row in range(height if self.active else 1):
                painter.fillRect(4 + column * 7, 24 - row * 3, 4, 2,
                                 QColor(LIME if self.active else "#415136"))


class Canvas(QWidget):
    changed = Signal()
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(380, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self.setAccessibleName("Image preview. Enable Draw boxes to add opaque redactions with the mouse.")
        self.pixmap = QPixmap()
        self.boxes = []
        self.anchor = None
        self.cursor_point = None
        self.drawing = False
        self.loading = False

    def image_rect(self):
        if self.pixmap.isNull():
            return QRectF()
        available = self.rect().adjusted(18, 18, -18, -18)
        size = self.pixmap.size().scaled(available.size(), Qt.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())

    def normalized(self, point):
        rect = self.image_rect()
        return QPointF(max(0, min(1, (point.x() - rect.x()) / rect.width())),
                       max(0, min(1, (point.y() - rect.y()) / rect.height())))

    def box_rect(self, box):
        rect = self.image_rect()
        return QRectF(rect.x() + box[0] * rect.width(), rect.y() + box[1] * rect.height(),
                      (box[2] - box[0]) * rect.width(), (box[3] - box[1]) * rect.height())

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#12171b"))
        painter.setPen(QColor("#1d252b"))
        for x in range(0, self.width(), 24):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 24):
            painter.drawLine(0, y, self.width(), y)
        if self.pixmap.isNull():
            painter.setPen(QColor(LIME))
            painter.setFont(QFont("Consolas", 22))
            painter.drawText(self.rect().adjusted(0, -28, 0, -28), Qt.AlignCenter, "[ DROP IMAGE HERE ]")
            painter.setFont(QFont("Consolas", 10))
            painter.setPen(QColor("#969fa7"))
            painter.drawText(self.rect().adjusted(0, 40, 0, 40), Qt.AlignCenter,
                             "DECODING PREVIEW…" if self.loading else "PNG / JPEG / WEBP  ·  OR SELECT FILES")
            return
        rect = self.image_rect()
        painter.fillRect(rect, QColor("#41464c"))
        painter.drawPixmap(rect.toRect(), self.pixmap)
        for index, box in enumerate(self.boxes):
            painter.fillRect(self.box_rect(box), Qt.black)
            painter.setPen(QPen(QColor(LIME), 1))
            painter.drawRect(self.box_rect(box))
        if self.anchor is not None and self.cursor_point is not None:
            current = QRectF(self.anchor, self.cursor_point).normalized()
            painter.setPen(QPen(QColor(LIME), 1, Qt.DashLine))
            painter.fillRect(current, QColor(0, 0, 0, 180))
            painter.drawRect(current)

    def mousePressEvent(self, event):
        if self.drawing and event.button() == Qt.LeftButton and self.image_rect().contains(event.position()):
            self.anchor = self.cursor_point = event.position()

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            rect = self.image_rect()
            self.cursor_point = QPointF(max(rect.left(), min(rect.right(), event.position().x())),
                                        max(rect.top(), min(rect.bottom(), event.position().y())))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            a, b = self.normalized(self.anchor), self.normalized(self.cursor_point)
            if abs(a.x() - b.x()) > .002 and abs(a.y() - b.y()) > .002 and len(self.boxes) < 100:
                self.boxes.append([min(a.x(), b.x()), min(a.y(), b.y()), max(a.x(), b.x()), max(a.y(), b.y())])
                self.changed.emit()
            self.anchor = self.cursor_point = None
            self.update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self.filesDropped.emit(files)
            event.acceptProposedAction()


@dataclass
class Item:
    source: str
    state: str = "READY"
    detail: str = "Select to inspect"
    request: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    boxes: list = field(default_factory=list)
    fingerprint: str = ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BitDeck · image workbench")
        self.resize(1180, 880)
        self.setMinimumSize(1000, 780)
        self.setAcceptDrops(True)
        self.items = []
        self.current_index = -1
        self.running_index = None
        self.inspect_index = None
        self.output_override = None
        self.closing = False
        self.runner = WorkerRunner(self)
        self.inspector = WorkerRunner(self)
        self.runner.completed.connect(self.export_finished)
        self.inspector.completed.connect(self.inspect_finished)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(12)
        top = QHBoxLayout()
        brand = label("BITDECK", "section")
        brand.setStyleSheet("font: bold 26px Consolas; color: #e3e6df; letter-spacing: 5px;")
        top.addWidget(brand)
        top.addWidget(label("IMAGE WORKBENCH   /   VOL. 01", "dim"))
        top.addStretch()
        top.addWidget(label("LOCAL FILES. HANDS-ON CONTROL.", "section"))
        top.addWidget(label("v0.1.0", "dim"))
        layout.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        workbench, work = panel("01  /  WORKBENCH")
        display = QHBoxLayout()
        self.lcd = label("STOPPED  /  NO INPUT", "display")
        display.addWidget(self.lcd, 1)
        self.spectrum = Spectrum()
        display.addWidget(self.spectrum)
        work.addLayout(display)
        self.canvas = Canvas()
        self.canvas.filesDropped.connect(self.add_files)
        self.canvas.changed.connect(self.boxes_changed)
        work.addWidget(self.canvas, 1)
        self.file_info = label("Load an image to tune your output.", "dim")
        self.file_info.setWordWrap(True)
        work.addWidget(self.file_info)
        transport = QHBoxLayout()
        add = button("+  FILES", self.pick_files, "Add images to the queue (Ctrl+O)")
        add.setShortcut("Ctrl+O")
        transport.addWidget(add)
        self.export_button = button(">  QUEUE EXPORT", self.queue_export, "Queue the selected image with the current settings (Ctrl+Return)", True)
        self.export_button.setShortcut("Ctrl+Return")
        transport.addWidget(self.export_button)
        self.cancel_button = button("■  CANCEL", self.cancel_active, "Stop the active export. Completed outputs are kept.")
        transport.addWidget(self.cancel_button)
        work.addLayout(transport)
        body.addWidget(workbench, 1)

        controls, knobs = panel("02  /  OUTPUT RACK")
        knobs.setSpacing(8)
        controls.setFixedWidth(292)
        knobs.addWidget(label("ENCODER", "section"))
        self.format = QComboBox()
        self.format.addItems(["WEBP", "JPEG", "PNG"])
        self.format.setAccessibleName("Output format")
        self.format.currentTextChanged.connect(self.format_changed)
        knobs.addWidget(self.format)
        quality_row = QHBoxLayout()
        quality_row.addWidget(label("QUALITY", "section"))
        quality_row.addStretch()
        self.quality_text = label("85 / 100", "section")
        quality_row.addWidget(self.quality_text)
        knobs.addLayout(quality_row)
        self.quality = QSlider(Qt.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(85)
        self.quality.setAccessibleName("Encoding quality")
        self.quality.valueChanged.connect(lambda value: self.quality_text.setText(f"{value:02} / 100"))
        knobs.addWidget(self.quality)
        knobs.addWidget(label("LONG EDGE  /  PIXELS", "section"))
        self.long_edge = QSpinBox()
        self.long_edge.setRange(0, 16384)
        self.long_edge.setSingleStep(100)
        self.long_edge.setSpecialValueText("ORIGINAL SIZE")
        self.long_edge.setAccessibleName("Maximum long edge in pixels; zero keeps original size")
        knobs.addWidget(self.long_edge)
        knobs.addWidget(label("Aspect ratio locked · never upscale", "dim"))
        knobs.addSpacing(4)
        knobs.addWidget(label("REDACTION", "section"))
        self.draw_button = button("DRAW BOXES", self.toggle_drawing, "Draw solid opaque boxes on the selected image")
        self.draw_button.setCheckable(True)
        knobs.addWidget(self.draw_button)
        redact_row = QHBoxLayout()
        redact_row.addWidget(button("ADD BY %", self.numeric_box, "Add a redaction using keyboard-accessible percentage coordinates"))
        redact_row.addWidget(button("CLEAR", self.clear_boxes, "Remove redaction boxes from this image"))
        knobs.addLayout(redact_row)
        self.box_count = label("00 boxes · opaque black only", "dim")
        knobs.addWidget(self.box_count)
        knobs.addSpacing(4)
        knobs.addWidget(label("PRIVACY", "section"))
        privacy = label("+ Metadata removed on export\n+ Original file kept\n+ No uploads or telemetry", "dim")
        privacy.setFixedHeight(64)
        privacy.setStyleSheet("color: #b0bca3; line-height: 1.5;")
        knobs.addWidget(privacy)
        knobs.addStretch()
        knobs.addWidget(label("DESTINATION", "section"))
        self.destination = label("BitDeck folder beside each original", "dim")
        self.destination.setWordWrap(True)
        knobs.addWidget(self.destination)
        knobs.addWidget(button("CHOOSE FOLDER…", self.choose_output, "Choose one destination for subsequent exports"))
        body.addWidget(controls)
        layout.addLayout(body, 1)

        queue_panel, queue_layout = panel("03  /  JOB QUEUE")
        queue_panel.setMinimumHeight(208)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["SOURCE", "STATE", "OUTPUT / RESULT", "SIZE"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 112)
        self.table.setColumnWidth(3, 125)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Image job queue")
        self.table.itemSelectionChanged.connect(self.selection_changed)
        queue_layout.addWidget(self.table)
        queue_actions = QHBoxLayout()
        self.queue_count = label("00 FILES  /  00 COMPLETE", "section")
        queue_actions.addWidget(self.queue_count)
        queue_actions.addStretch()
        self.open_output_button = button("OPEN OUTPUT", self.open_output, "Open the selected completed output folder")
        queue_actions.addWidget(self.open_output_button)
        self.undo_button = button("UNDO EXPORT", self.undo_export, "Move the selected output to the Recycle Bin. Never permanently deletes.")
        queue_actions.addWidget(self.undo_button)
        queue_layout.addLayout(queue_actions)
        layout.addWidget(queue_panel)
        footer = QHBoxLayout()
        self.status = label("READY  ·  Drop files to start a session.", "dim")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(120)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        footer.addWidget(self.progress)
        footer.addWidget(label("40 MP MAX  /  64 MiB IN & OUT", "section"))
        layout.addLayout(footer)
        self.refresh_controls()

    def selected(self):
        return self.items[self.current_index] if 0 <= self.current_index < len(self.items) else None

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add images", "", "Images (*.png *.jpg *.jpeg *.webp)")
        self.add_files(paths)

    def add_files(self, files):
        known = {item.source for item in self.items}
        first_new = None
        for file in files[:200]:
            path = Path(file).resolve()
            if len(self.items) >= 200:
                self.status.setText("Queue limit reached: 200 files per session.")
                break
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
                self.status.setText("Choose PNG, JPEG or WebP files. Other formats are not supported yet.")
                continue
            if str(path) not in known:
                first_new = len(self.items) if first_new is None else first_new
                self.items.append(Item(str(path)))
                known.add(str(path))
        self.refresh_table()
        if first_new is not None:
            self.table.selectRow(first_new)

    def refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            result = item.result
            size = human_bytes(result["output_bytes"]) if result.get("output_bytes") else "—"
            for column, text in enumerate([Path(item.source).name, item.state, item.detail, size]):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text if column else item.source)
                if column == 1:
                    cell.setForeground(QColor(LIME if item.state == "DONE" else AMBER if item.state in {"WORKING", "QUEUED"} else "#9ba5ad"))
                self.table.setItem(row, column, cell)
        self.table.blockSignals(False)
        complete = sum(item.state == "DONE" for item in self.items)
        self.queue_count.setText(f"{len(self.items):02} FILES  /  {complete:02} COMPLETE")
        self.refresh_controls()

    def selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        self.current_index = rows[0].row() if rows else -1
        item = self.selected()
        self.canvas.boxes = item.boxes if item else []
        self.canvas.pixmap = QPixmap()
        self.canvas.loading = bool(item)
        self.canvas.update()
        self.boxes_changed()
        self.refresh_controls()
        if item:
            self.file_info.setText(Path(item.source).name)
            self.lcd.setText("READING  /  INPUT")
            if self.inspector.busy:
                self.inspector.stop("Selection changed.")
            else:
                self.inspect_selected()

    def inspect_selected(self):
        item = self.selected()
        if item and not self.closing:
            self.inspect_index = self.current_index
            self.inspector.start({"operation": "inspect", "source": item.source})

    def inspect_finished(self, result):
        if self.closing:
            return
        if self.inspect_index != self.current_index or result.get("error") == "Selection changed.":
            self.inspect_selected()
            return
        self.canvas.loading = False
        if result["ok"]:
            pixmap = QPixmap()
            try:
                pixmap.loadFromData(base64.b64decode(result["preview"], validate=True), "PNG")
            except (KeyError, ValueError):
                self.status.setText("Could not display preview.")
                return
            self.canvas.pixmap = pixmap
            item = self.selected()
            if item.fingerprint and item.fingerprint != result["sha256"]:
                item.boxes.clear()
                self.boxes_changed()
            item.fingerprint = result["sha256"]
            self.file_info.setText(f"{Path(self.selected().source).name}   /   {result['width']} × {result['height']} px   /   {result['format']}   /   {human_bytes(result['input_bytes'])}")
            self.lcd.setText(f"{result['width']:04} × {result['height']:04}  /  {result['format']}")
            self.status.setText("INPUT READY  ·  Tune the rack, then queue an export.")
        else:
            self.lcd.setText("INPUT  /  UNAVAILABLE")
            self.status.setText(result.get("error", "Preview unavailable."))
        self.canvas.update()
        self.refresh_controls()

    def format_changed(self, fmt):
        self.quality.setEnabled(fmt != "PNG")
        self.quality_text.setText("LOSSLESS" if fmt == "PNG" else f"{self.quality.value():02} / 100")

    def toggle_drawing(self):
        self.canvas.drawing = self.draw_button.isChecked()
        self.canvas.setCursor(Qt.CrossCursor if self.canvas.drawing else Qt.ArrowCursor)

    def boxes_changed(self):
        self.box_count.setText(f"{len(self.canvas.boxes):02} boxes · opaque black only")

    def clear_boxes(self):
        self.canvas.boxes.clear()
        self.canvas.update()
        self.boxes_changed()

    def numeric_box(self):
        if not self.selected() or self.canvas.pixmap.isNull():
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Add opaque box · percentages")
        layout = QGridLayout(dialog)
        inputs = []
        for row, (text, value) in enumerate([("Left %", 10), ("Top %", 10), ("Right %", 30), ("Bottom %", 30)]):
            control = QSpinBox()
            control.setRange(0, 100)
            control.setValue(value)
            control.setAccessibleName(text)
            layout.addWidget(label(text), row, 0)
            layout.addWidget(control, row, 1)
            inputs.append(control)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, 4, 0, 1, 2)
        if dialog.exec() == QDialog.Accepted:
            left, top, right, bottom = [control.value() / 100 for control in inputs]
            if left >= right or top >= bottom or len(self.canvas.boxes) >= 100:
                self.status.setText("Use a positive box area. Maximum 100 boxes.")
                return
            self.canvas.boxes.append([left, top, right, bottom])
            self.canvas.update()
            self.boxes_changed()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.output_override = folder
            self.destination.setText(folder)

    def queue_export(self):
        item = self.selected()
        if not item or item.state in {"QUEUED", "WORKING"} or self.canvas.pixmap.isNull():
            return
        item.request = {"operation": "export", "source": item.source,
                        "output_dir": self.output_override or str(Path(item.source).parent / "BitDeck"),
                        "format": self.format.currentText(), "quality": self.quality.value(),
                        "expected_sha256": item.fingerprint,
                        "long_edge": self.long_edge.value(), "redactions": [list(box) for box in item.boxes]}
        item.state = "QUEUED"
        item.detail = f"{item.request['format']} · settings captured"
        self.refresh_table()
        self.start_next()

    def start_next(self):
        if self.closing or self.runner.busy:
            return
        for index, item in enumerate(self.items):
            if item.state == "QUEUED":
                self.running_index = index
                item.state = "WORKING"
                item.detail = "Encoding in worker process"
                self.status.setText(f"PROCESSING  ·  {Path(item.source).name}")
                self.spectrum.active = True
                self.spectrum.update()
                self.progress.setRange(0, 0)
                self.refresh_table()
                self.runner.start(item.request)
                return
        self.running_index = None
        self.spectrum.active = False
        self.spectrum.update()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.refresh_controls()

    def export_finished(self, result):
        if self.closing or self.running_index is None:
            return
        item = self.items[self.running_index]
        self.running_index = None
        item.result = result
        if result["ok"]:
            item.state = "DONE"
            item.detail = f"{result['width']}×{result['height']} · {Path(result['output']).name}"
            self.status.setText(f"SAVED  ·  {human_bytes(result['input_bytes'])} → {human_bytes(result['output_bytes'])}  ·  Metadata removed")
        else:
            item.state = "CANCELLED" if result.get("error", "").startswith("Cancelled") else "FAILED"
            item.detail = result.get("error", "Export failed.")
            self.status.setText(item.detail)
        self.refresh_table()
        QTimer.singleShot(0, self.start_next)

    def cancel_active(self):
        # Stop all queued work, so Cancel never immediately launches another export.
        for item in self.items:
            if item.state == "QUEUED":
                item.state, item.detail = "CANCELLED", "Cancelled before processing"
        self.runner.stop()
        self.refresh_table()

    def refresh_controls(self):
        item = self.selected()
        self.export_button.setEnabled(bool(item and item.state not in {"QUEUED", "WORKING"} and not self.canvas.pixmap.isNull()))
        self.cancel_button.setEnabled(self.runner.busy or self.running_index is not None)
        completed = bool(item and item.state == "DONE" and item.result.get("output"))
        self.open_output_button.setEnabled(completed)
        self.undo_button.setEnabled(completed)
        self.draw_button.setEnabled(bool(item and not self.canvas.pixmap.isNull()))

    def open_output(self):
        item = self.selected()
        if item and item.result.get("output"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.result["output"]).parent)))

    def undo_export(self):
        item = self.selected()
        if not item or item.state != "DONE":
            return
        output = Path(item.result["output"])
        if QMessageBox.question(self, "Undo export", f"Move {output.name} to the Recycle Bin?\nThe original stays in place.") != QMessageBox.Yes:
            return
        # Refuse if the output was replaced since this job, rather than trashing
        # an unrelated file that later acquired its name.
        stat = output.stat() if output.exists() else None
        if not stat or [stat.st_ino, stat.st_size, stat.st_mtime_ns] != item.result.get("identity"):
            self.status.setText("Output changed or disappeared. Undo refused; no file was deleted.")
            return
        if QFile.moveToTrash(str(output)):
            item.state, item.detail = "UNDONE", "Output moved to Recycle Bin"
            self.status.setText("UNDONE  ·  Output moved to Recycle Bin. Original kept.")
            self.refresh_table()
        else:
            self.status.setText("Recycle Bin unavailable. Output kept; nothing permanently deleted.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.runner.busy and QMessageBox.question(self, "Stop processing?", "Close BitDeck and stop pending work?\nCompleted outputs are kept.") != QMessageBox.Yes:
            event.ignore()
            return
        self.closing = True
        self.runner.shutdown()
        self.inspector.shutdown()
        event.accept()


def create_application():
    application = QApplication(sys.argv[:1])
    # Explicit loading also works in desktop sessions with restricted font discovery.
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf"):
            if (fonts / name).exists():
                QFontDatabase.addApplicationFont(str(fonts / name))
    application.setFont(QFont("Segoe UI", 10))
    application.setApplicationName("BitDeck")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    return application


def main(argv=None):
    parser = argparse.ArgumentParser(description="BitDeck image workbench")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--screenshot", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    application = create_application()
    window = MainWindow()
    window.show()
    if args.files:
        QTimer.singleShot(0, lambda: window.add_files(args.files))
    if args.screenshot:
        def capture():
            if window.inspector.busy:
                QTimer.singleShot(200, capture)
                return
            window.grab().save(args.screenshot)
            window.closing = True
            window.runner.shutdown()
            window.inspector.shutdown()
            application.quit()
        QTimer.singleShot(1500, capture)
    code = application.exec()
    window.closing = True
    window.close()
    window.deleteLater()
    from PySide6.QtCore import QEvent
    application.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()
    return code
