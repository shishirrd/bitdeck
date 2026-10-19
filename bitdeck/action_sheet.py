"""Modeless action settings; no nested dialog loop during a native file drop."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QSpinBox, QComboBox, QLineEdit, QHBoxLayout
from .app import label, button
from .motion import show_gently


class ActionSheet(QDialog):
    confirmed = Signal(dict)
    CONFIGURED = {"resize_image", "compress_image", "pdf_to_png", "pdf_to_jpeg", "pdf_rotate", "pdf_protect"}

    def __init__(self, key, paths, anchor):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("BitDeck · " + key.replace("_", " "))
        self.setMinimumWidth(390)
        self.key = key
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        titles = {"resize_image": "RESIZE COPIES", "compress_image": "COMPRESS COPIES", "pdf_to_png": "PDF TO PNG",
                  "pdf_to_jpeg": "PDF TO JPEG", "pdf_rotate": "ROTATE PAGES", "pdf_protect": "PROTECT PDF"}
        layout.addWidget(label(titles[key], "display"))
        layout.addWidget(label(f"{len(paths)} file(s) · originals kept", "dim"))
        form = QFormLayout()
        if key in {"pdf_to_png", "pdf_to_jpeg", "resize_image", "compress_image"}:
            options = {"resize_image": ("long_edge", "Maximum long edge (px)", 1600, 1, 16384),
                       "compress_image": ("quality", "JPEG / WebP quality", 72, 1, 100),
                       "pdf_to_png": ("dpi", "Resolution (DPI)", 150, 72, 300),
                       "pdf_to_jpeg": ("dpi", "Resolution (DPI)", 150, 72, 300)}
            name, title, default, low, high = options[key]
            field = QSpinBox()
            field.setRange(low, high)
            field.setValue(default)
            field.setAccessibleName(title)
            self.fields[name] = field
            form.addRow(title, field)
        elif key == "pdf_rotate":
            field = QComboBox()
            field.addItems(["90", "180", "270"])
            self.fields["degrees"] = field
            form.addRow("Clockwise rotation", field)
        elif key == "pdf_protect":
            for name, title in [("password", "New password"), ("repeat", "Confirm password")]:
                field = QLineEdit()
                field.setEchoMode(QLineEdit.Password)
                field.setMaxLength(128)
                field.setAccessibleName(title)
                self.fields[name] = field
                form.addRow(title, field)
        layout.addLayout(form)
        self.feedback = label("PNG compression is lossless." if key == "compress_image" else "Use 8–128 characters." if key == "pdf_protect" else "A separate output copy will be saved.", "dim")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        row = QHBoxLayout()
        cancel = button("CANCEL", self.reject, "Close without processing")
        cancel.setAutoDefault(False)
        row.addWidget(cancel)
        self.submit_button = button("PROCESS COPY", self.submit, "Apply these settings and start processing", True)
        self.submit_button.setDefault(True)
        row.addWidget(self.submit_button)
        layout.addLayout(row)
        self.adjustSize()
        bounds = (QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(max(bounds.left(), min(bounds.right()-self.width()+1, anchor.x()-self.width()//2)),
                  max(bounds.top(), min(bounds.bottom()-self.height()+1, anchor.y()-self.height()//2)))

    def present(self):
        show_gently(self)
        self.raise_()
        self.activateWindow()
        next(iter(self.fields.values())).setFocus()

    def submit(self):
        if not self.submit_button.isEnabled():
            return
        if self.key == "pdf_protect":
            password = self.fields["password"].text()
            if not 8 <= len(password) <= 128 or password != self.fields["repeat"].text():
                self.feedback.setText("Use 8–128 characters and matching passwords.")
                return
            values = {"password": password}
            for field in self.fields.values():
                field.clear()
        else:
            values = {name: int(field.currentText()) if isinstance(field, QComboBox) else field.value() for name, field in self.fields.items()}
        self.submit_button.setEnabled(False)
        self.confirmed.emit(values)
        self.accept()

    def done(self, result):
        if self.key == "pdf_protect":
            for field in self.fields.values():
                field.clear()
        super().done(result)
