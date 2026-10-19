"""PDF page assembly, inspection and export. All parsing stays in workers."""
import base64
from pathlib import Path
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QFileDialog, QComboBox, QLineEdit, QSpinBox, QInputDialog, QMessageBox, QFormLayout, QPlainTextEdit)
from .app import label, button
from .runner import WorkerRunner


class PDFWindow(QWidget):
    def __init__(self, batch):
        super().__init__()
        self.batch = batch
        self.setWindowTitle("BitDeck · PDF controls")
        self.resize(1100, 800)
        self.sources, self.fingerprints, self.passwords = [], {}, {}
        self.page_counts = {}
        self.waiting = []
        self.current = None
        self.folder = None
        self.inspector = WorkerRunner(self)
        self.inspector.completed.connect(self.inspected)
        self.previewer = WorkerRunner(self)
        self.previewer.completed.connect(self.previewed)
        self.preview_identity = None
        self.pending_preview = None
        self.closing = False
        layout = QVBoxLayout(self)
        layout.addWidget(label("BITDECK  /  PDF CONTROLS", "display"))
        row = QHBoxLayout()
        row.addWidget(button("+ PDF FILES", self.pick, "Append PDFs to the page arrangement"))
        row.addWidget(button("CLEAR / RELOAD", self.clear, "Discard this arrangement and release stored passwords"))
        row.addWidget(button("OUTPUT FOLDER", self.choose_folder, "Choose where copies are written"))
        layout.addLayout(row)
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(label("PAGE ARRANGEMENT  /  drag rows to reorder", "section"))
        self.pages = QListWidget()
        self.pages.setDragDropMode(QAbstractItemView.InternalMove)
        self.pages.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pages.currentItemChanged.connect(self.preview_page)
        left.addWidget(self.pages)
        controls = QHBoxLayout()
        controls.addWidget(button("REMOVE SELECTED", self.remove, "Omit pages from the arranged PDF"))
        controls.addWidget(button("ROTATE +90°", self.rotate, "Rotate selected pages in the arranged PDF"))
        controls.addWidget(button("UP", lambda: self.move(-1), "Move selected pages up"))
        controls.addWidget(button("DOWN", lambda: self.move(1), "Move selected pages down"))
        left.addLayout(controls)
        left.addWidget(button("SAVE ARRANGEMENT", self.organize, "Merge, reorder, omit and rotate pages into a new PDF", True))
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = label("Select a page to preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(340, 300)
        right.addWidget(self.preview, 1)
        right.addWidget(label("DOCUMENT ACTIONS  /  selected source PDF", "section"))
        form = QFormLayout()
        self.document = QComboBox()
        self.range = QLineEdit()
        self.range.setPlaceholderText("All pages, or 1-3,5,8-6 (output order)")
        self.action = QComboBox()
        for title, key in [("Extract / reorder pages to PDF", "pdf_organize"), ("Split selected pages into separate PDFs", "pdf_split"), ("Selected pages to PNG", "pdf_to_png"), ("Selected pages to JPEG", "pdf_to_jpeg"), ("Selected pages to text", "pdf_to_text"), ("Rotate selected pages", "pdf_rotate"), ("Compress selected pages (lossless)", "pdf_compress"), ("Protect with AES-256", "pdf_protect"), ("Save decrypted copy", "pdf_unlock"), ("Extract embedded images", "pdf_extract"), ("Remove document metadata", "pdf_metadata"), ("Set document metadata", "pdf_edit_metadata")]:
            self.action.addItem(title, key)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 300)
        self.dpi.setValue(150)
        form.addRow("Document", self.document)
        form.addRow("Pages", self.range)
        form.addRow("Action", self.action)
        form.addRow("Image DPI", self.dpi)
        right.addLayout(form)
        right.addWidget(button("QUEUE DOCUMENT ACTION", self.export, "Apply the action to the page range and queue a copy", True))
        self.tags = QPlainTextEdit("Metadata appears after loading a PDF.")
        self.tags.setReadOnly(True)
        self.tags.setMaximumHeight(100)
        right.addWidget(self.tags)
        self.document.currentIndexChanged.connect(self.show_metadata)
        body.addLayout(right, 1)
        layout.addLayout(body, 1)
        self.status = label("Original files are kept. Metadata removal is not document-content sanitization.")
        layout.addWidget(self.status)
        self.metadata = {}

    def pick(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF (*.pdf)")
        self.add_files(paths)

    def add_files(self, paths):
        known = set(self.sources + self.waiting + ([self.current] if self.current else []))
        for path in paths:
            source = str(Path(path).resolve())
            if Path(path).suffix.lower() == ".pdf" and source not in known and len(known) < 50:
                self.waiting.append(source)
                known.add(source)
        self.next_inspection()

    def next_inspection(self):
        if self.inspector.busy or not self.waiting:
            return
        self.current = self.waiting.pop(0)
        self.status.setText("Reading " + Path(self.current).name)
        self.inspector.start({"operation": "pdf_inspect", "source": self.current, "input_password": self.passwords.get(self.current, "")})

    def inspected(self, result):
        if self.closing:
            return
        source = self.current
        if not result["ok"]:
            if "password" in result.get("error", "").lower():
                password, ok = QInputDialog.getText(self, "PDF input password", Path(source).name, QLineEdit.Password)
                if ok:
                    self.passwords[source] = password
                    self.inspector.start({"operation": "pdf_inspect", "source": source, "input_password": password})
                    return
            self.status.setText(result.get("error", "Could not inspect PDF."))
            self.passwords.pop(source, None)
        elif len(self.sources) >= 50 or self.pages.count() + result["pages"] > 200:
            self.status.setText("Arrangement limit: 50 documents / 200 pages.")
        else:
            index = len(self.sources)
            self.sources.append(source)
            self.fingerprints[source] = result["sha256"]
            self.metadata[source] = result["metadata"]
            self.page_counts[source] = result["pages"]
            self.document.addItem(Path(source).name, source)
            for page in range(result["pages"]):
                item = QListWidgetItem(f"{Path(source).name} · page {page + 1} · 0°")
                item.setData(Qt.UserRole, [index, page, 0])
                self.pages.addItem(item)
            self.show_metadata()
            self.status.setText(f"Loaded {len(self.sources)} PDF(s), {self.pages.count()} arranged pages.")
        self.current = None
        self.next_inspection()

    def show_metadata(self):
        tags = self.metadata.get(self.document.currentData(), {})
        self.tags.setPlainText("\n".join(f"{k}: {v}" for k, v in tags.items()) or "No document Info metadata.")

    def preview_page(self, item, _previous=None):
        if item is None or self.closing:
            return
        source_index, page, rotation = item.data(Qt.UserRole)
        if not 0 <= source_index < len(self.sources):
            return
        self.pending_preview = (self.sources[source_index], page, rotation)
        self.start_preview()

    def start_preview(self):
        if self.previewer.busy or self.pending_preview is None:
            return
        self.preview_identity, self.pending_preview = self.pending_preview, None
        source, page, _ = self.preview_identity
        self.previewer.start({"operation": "pdf_preview", "source": source, "page": page,
                              "input_password": self.passwords.get(source, ""), "fingerprints": self.fingerprints})

    def previewed(self, result):
        if self.closing:
            return
        if self.pending_preview is None:
            if result["ok"]:
                from PySide6.QtGui import QTransform
                pixmap = QPixmap()
                pixmap.loadFromData(base64.b64decode(result["preview"]), "PNG")
                pixmap = pixmap.transformed(QTransform().rotate(self.preview_identity[2]))
                self.preview.setPixmap(pixmap.scaled(420, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview.setText(result.get("error", "Preview unavailable."))
        self.start_preview()

    def remove(self):
        for item in self.pages.selectedItems():
            self.pages.takeItem(self.pages.row(item))

    def rotate(self):
        for item in self.pages.selectedItems():
            source, page, rotation = item.data(Qt.UserRole)
            rotation = (rotation + 90) % 360
            item.setData(Qt.UserRole, [source, page, rotation])
            item.setText(f"{Path(self.sources[source]).name} · page {page + 1} · {rotation}°")
        self.preview_page(self.pages.currentItem())

    def move(self, direction):
        rows = sorted((self.pages.row(i) for i in self.pages.selectedItems()), reverse=direction > 0)
        for row in rows:
            target = row + direction
            if 0 <= target < self.pages.count():
                item = self.pages.takeItem(row)
                self.pages.insertItem(target, item)
                item.setSelected(True)
        selected = self.pages.selectedItems()
        if selected:
            self.pages.setCurrentItem(selected[0], QItemSelectionModel.NoUpdate)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.folder = folder
            self.status.setText("Output: " + folder)

    def common(self, source):
        return {"source": source, "output_dir": self.folder or str(Path(source).parent / "BitDeck"),
                "fingerprints": dict(self.fingerprints), "input_passwords": dict(self.passwords),
                "input_password": self.passwords.get(source, ""), "requires_password": bool(self.passwords)}

    def organize(self):
        if not self.sources or not self.pages.count() or self.inspector.busy:
            self.status.setText("Load PDFs and keep at least one page before exporting.")
            return
        self.batch.submit([{**self.common(self.sources[0]), "operation": "pdf_organize", "sources": list(self.sources),
                            "page_plan": [self.pages.item(i).data(Qt.UserRole) for i in range(self.pages.count())]}])

    def export(self):
        source = self.document.currentData()
        if not source:
            return
        operation = self.action.currentData()
        job = {**self.common(source), "operation": operation, "page_range": self.range.text(), "dpi": self.dpi.value()}
        if operation == "pdf_organize":
            # Range parsing is pure validation; PDF parsing remains in workers.
            from .page_ranges import page_indices
            # Original page count is independent of pages omitted from arrangement.
            count = self.page_counts[source]
            try:
                indices = page_indices(self.range.text(), count)
            except ValueError as error:
                self.status.setText(str(error))
                return
            job.update(sources=[source], page_plan=[[0, i, 0] for i in indices])
        elif operation == "pdf_rotate":
            degrees, ok = QInputDialog.getItem(self, "Rotate pages", "Clockwise degrees", ["90", "180", "270"], 0, False)
            if not ok:
                return
            job["degrees"] = int(degrees)
        elif operation == "pdf_protect":
            password, ok = QInputDialog.getText(self, "Protect PDF", "New password (8–128 characters)", QLineEdit.Password)
            if not ok:
                return
            if not 8 <= len(password) <= 128:
                self.status.setText("Use a password of 8–128 characters.")
                return
            job["password"] = password
        elif operation == "pdf_edit_metadata":
            values = {}
            for key in ("Title", "Author", "Subject", "Keywords"):
                value, ok = QInputDialog.getText(self, "PDF metadata", key, text=self.metadata.get(source, {}).get("/" + key, ""))
                if not ok:
                    return
                values["/" + key] = value
            job["metadata"] = values
        self.batch.submit([job])

    def clear(self):
        if self.inspector.busy or self.previewer.busy:
            self.status.setText("Wait for inspection or preview to finish before clearing.")
            return
        self.pages.blockSignals(True)
        self.pages.clear()
        self.pages.blockSignals(False)
        self.sources.clear()
        self.fingerprints.clear()
        self.passwords.clear()
        self.metadata.clear()
        self.page_counts.clear()
        self.waiting.clear()
        self.document.clear()
        self.preview.clear()
        self.status.setText("Arrangement cleared. Add PDFs to begin.")

    def closeEvent(self, event):
        self.closing = True
        self.waiting.clear()
        self.pending_preview = None
        self.passwords.clear()
        self.inspector.shutdown()
        self.previewer.shutdown()
        self.current = None
        self.clear()
        event.accept()

    def showEvent(self, event):
        self.closing = False
        super().showEvent(event)
