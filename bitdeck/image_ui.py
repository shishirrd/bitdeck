"""Image tools attached to the existing workbench and its oriented canvas."""
import base64
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QSpinBox, QCheckBox,
    QLineEdit, QPlainTextEdit, QColorDialog, QHBoxLayout, QDoubleSpinBox, QMessageBox)
from .app import button, label
from .runner import WorkerRunner


class ImageTools(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("BitDeck · metadata, crop & annotation")
        self.resize(470, 700)
        self.color = "#ffcc00"
        self.preview_runner = WorkerRunner(self)
        self.preview_runner.completed.connect(self.previewed)
        layout = QVBoxLayout(self)
        layout.addWidget(label("IMAGE TOOLS  /  selected image", "display"))
        form = QFormLayout()
        self.policy = QComboBox()
        for text, value in [("Remove all metadata (default)", "remove_all"), ("Keep common EXIF except GPS", "remove_gps"), ("Keep common EXIF including GPS", "keep_exif")]:
            self.policy.addItem(text, value)
        self.rotation = QComboBox()
        self.rotation.addItems(["0", "90", "180", "270"])
        self.horizontal = QCheckBox("Flip horizontally")
        self.vertical = QCheckBox("Flip vertically")
        self.tool = QComboBox()
        self.tool.addItems(["Redact", "Crop", "Box", "Arrow", "Marker", "Text", "Number"])
        self.tool.currentTextChanged.connect(self.tool_changed)
        self.text = QLineEdit("Note")
        self.text.setMaxLength(500)
        self.stroke = QSpinBox()
        self.stroke.setRange(1, 100)
        self.stroke.setValue(4)
        self.font = QSpinBox()
        self.font.setRange(8, 256)
        self.font.setValue(24)
        form.addRow("Metadata", self.policy)
        form.addRow("Clockwise rotation", self.rotation)
        form.addRow(self.horizontal)
        form.addRow(self.vertical)
        form.addRow("Draw on canvas", self.tool)
        form.addRow("Text / step number", self.text)
        form.addRow("Stroke (source pixels)", self.stroke)
        form.addRow("Font (source pixels)", self.font)
        layout.addLayout(form)
        layout.addWidget(button("ANNOTATION COLOR", self.choose_color, "Choose the color for subsequent annotations"))
        layout.addWidget(label("Crop: draw on the image or enter Left / Top / Right / Bottom %."))
        crop_row = QHBoxLayout()
        self.crop_values = []
        for name, value in [("Left", 0), ("Top", 0), ("Right", 100), ("Bottom", 100)]:
            control = QDoubleSpinBox()
            control.setRange(0, 100)
            control.setValue(value)
            control.setSuffix("%")
            control.setAccessibleName(name + " crop percent")
            crop_row.addWidget(control)
            self.crop_values.append(control)
        layout.addLayout(crop_row)
        ratios = QHBoxLayout()
        ratios.addWidget(button("APPLY CROP", self.apply_crop, "Use the percentage crop rectangle"))
        for title, ratio in [("1:1", 1), ("4:3", 4/3), ("16:9", 16/9)]:
            ratios.addWidget(button(title, lambda checked=False, r=ratio: self.ratio_crop(r), "Centered crop at this aspect ratio"))
        layout.addLayout(ratios)
        row = QHBoxLayout()
        row.addWidget(button("UNDO MARK", self.undo_mark, "Remove the latest annotation"))
        row.addWidget(button("RESET EDITS", self.reset, "Clear crop, transforms and annotations for this image"))
        layout.addLayout(row)
        layout.addWidget(button("PREVIEW OUTPUT", self.preview, "Render all edits in a worker before exporting", True))
        note = label("Marks use the original oriented image; then crop → rotate → flip → resize.\nEXIF retention drops maker notes, XMP/text/profiles and original thumbnails.\nGPS removal clears standard GPS tags; descriptive text may still identify a place.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.metadata.setMaximumHeight(150)
        layout.addWidget(self.metadata)
        self.policy.currentIndexChanged.connect(self.capture)
        self.rotation.currentIndexChanged.connect(self.capture)
        self.horizontal.toggled.connect(self.capture)
        self.vertical.toggled.connect(self.capture)
        window.canvas.selectionMade.connect(self.selection)
        self.syncing = False

    def sync(self):
        self.syncing = True
        item = self.window.selected()
        edits = item.edits if item else {}
        self.policy.setCurrentIndex(max(0, self.policy.findData(edits.get("metadata_policy", "remove_all"))))
        self.rotation.setCurrentText(str(edits.get("rotation", 0)))
        self.horizontal.setChecked(edits.get("flip_horizontal", False))
        self.vertical.setChecked(edits.get("flip_vertical", False))
        for control, value in zip(self.crop_values, edits.get("crop", [0, 0, 1, 1])):
            control.setValue(value * 100)
        self.metadata.setPlainText("\n".join(f"{key}: {value}" for key, value in (item.metadata if item else {}).items()) or "No readable metadata.")
        self.syncing = False

    def capture(self, *_):
        if self.syncing:
            return
        item = self.window.selected()
        if item:
            item.edits.update(metadata_policy=self.policy.currentData(), rotation=int(self.rotation.currentText()),
                              flip_horizontal=self.horizontal.isChecked(), flip_vertical=self.vertical.isChecked())

    def tool_changed(self, text):
        self.window.canvas.tool = text.lower()
        self.window.draw_button.setChecked(True)
        self.window.toggle_drawing()

    def selection(self, box):
        item = self.window.selected()
        if not item:
            return
        kind = self.tool.currentText().lower()
        if kind == "crop":
            item.edits["crop"] = box
            for control, value in zip(self.crop_values, box):
                control.setValue(value * 100)
        else:
            annotations = item.edits.setdefault("annotations", [])
            if len(annotations) >= 100:
                return
            annotations.append({"kind": kind, "box": box, "color": self.color, "width": self.stroke.value(),
                                "text": self.text.text() or "1", "size": self.font.value()})
            if kind == "number":
                try:
                    self.text.setText(str(int(self.text.text()) + 1))
                except ValueError:
                    self.text.setText("2")
        self.window.canvas.update()

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self)
        if color.isValid():
            self.color = color.name()

    def apply_crop(self):
        item = self.window.selected()
        values = [control.value() / 100 for control in self.crop_values]
        if item and values[0] < values[2] and values[1] < values[3]:
            item.edits["crop"] = values
            self.window.canvas.update()
        else:
            QMessageBox.information(self, "Crop", "Crop width and height must be positive.")

    def ratio_crop(self, ratio):
        item = self.window.selected()
        if not item or not item.dimensions:
            return
        width, height = item.dimensions
        w, h = min(1, ratio * height / width), min(1, width / (ratio * height))
        values = [(1-w)/2, (1-h)/2, (1+w)/2, (1+h)/2]
        for control, value in zip(self.crop_values, values):
            control.setValue(value * 100)
        item.edits["crop"] = values
        self.window.canvas.update()

    def undo_mark(self):
        item = self.window.selected()
        if item and item.edits.get("annotations"):
            item.edits["annotations"].pop()
            self.window.canvas.update()

    def reset(self):
        item = self.window.selected()
        if item:
            item.edits.clear()
            self.sync()
            self.window.canvas.update()

    def preview(self):
        item = self.window.selected()
        if item and not self.preview_runner.busy:
            self.capture()
            self.preview_runner.start({"operation": "inspect", "source": item.source, "expected_sha256": item.fingerprint,
                **deepcopy(item.edits), "redactions": deepcopy(item.boxes), "long_edge": self.window.long_edge.value()})

    def previewed(self, result):
        if self.window.closing:
            return
        if not result["ok"]:
            QMessageBox.information(self, "Preview", result.get("error", "Preview failed."))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Output preview · {result['width']} × {result['height']}")
        layout = QVBoxLayout(dialog)
        image = label("")
        pixmap = QPixmap()
        pixmap.loadFromData(base64.b64decode(result["preview"]), "PNG")
        image.setPixmap(pixmap.scaled(900, 650, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(image)
        layout.addWidget(button("CLOSE", dialog.accept, "Return to editing"))
        dialog.exec()
