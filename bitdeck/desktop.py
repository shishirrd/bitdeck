"""Resident tray application: drag -> Shift -> type-aware action -> result card."""
import argparse
from pathlib import Path
import sys
import subprocess

from PySide6.QtCore import QFile, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QVBoxLayout)

from .actions import category
from .app import MainWindow, create_application, human_bytes, label, button
from .radial import CursorMenu
from .runner import WorkerRunner
from .trigger import DragWatcher
from .ipc import InstanceServer, handoff
from .theming import ThemeManager


def tray_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#252930"))
    painter = QPainter(pixmap)
    for x, height in [(5, 10), (11, 22), (17, 16), (23, 26)]:
        painter.fillRect(x, 29 - height, 4, height, QColor("#c4ee70"))
    painter.end()
    return QIcon(pixmap)


class ResultCard(QFrame):
    def __init__(self, title, detail, result=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.result = result or {}
        self.setObjectName("panel")
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(label(title, "section"), 1)
        heading.addWidget(button("×", self.close, "Dismiss result"))
        layout.addLayout(heading)
        self.detail = label(detail)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        if result and result.get("ok"):
            row = QHBoxLayout()
            row.addWidget(button("OPEN FOLDER", self.open_folder, "Open the output folder"))
            row.addWidget(button("UNDO", self.undo, "Move outputs to Recycle Bin; never permanently delete"))
            layout.addLayout(row)
        self.adjustSize()

    def popup(self):
        screen = self.screen().availableGeometry()
        self.move(screen.right() - self.width() - 18, screen.bottom() - self.height() - 18)
        self.show()

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.result["output"]).parent)))

    def undo(self):
        paths = self.result.get("outputs", [self.result["output"]])
        identities = self.result.get("identities", [self.result["identity"]])
        if QMessageBox.question(self, "Undo outputs", f"Move {len(paths)} output file(s) to the Recycle Bin?\nOriginals stay in place.") != QMessageBox.Yes:
            return
        removed = 0
        remaining_paths, remaining_identities = [], []
        for name, identity in zip(paths, identities):
            path = Path(name)
            try:
                stat = path.stat()
                unchanged = [stat.st_ino, stat.st_size, stat.st_mtime_ns] == identity
            except OSError:
                unchanged = False
            if unchanged and QFile.moveToTrash(str(path)):
                removed += 1
            else:
                remaining_paths.append(name)
                remaining_identities.append(identity)
        self.result["outputs"], self.result["identities"] = remaining_paths, remaining_identities
        self.detail.setText(f"Moved {removed} output(s) to Recycle Bin. {len(remaining_paths)} kept or unavailable. No permanent deletion.")


class Desktop(QObject):
    def __init__(self, application, single_instance=True, theme_cache=None):
        super().__init__(application)
        self.application = application
        self.application.setQuitOnLastWindowClosed(False)
        self.menu = CursorMenu()
        self.themes = ThemeManager(application, self.menu, theme_cache)
        self.menu.actionChosen.connect(self.choose)
        self.menu.browseRequested.connect(self.browse)
        self.watcher = DragWatcher(self)
        self.watcher.activated.connect(lambda point: self.menu.popup(point))
        self.watcher.cancelled.connect(lambda: self.menu.hide() if self.menu.drag_mode else None)
        self.watcher.start()
        from .batch import BatchWindow
        self.batch = BatchWindow()
        self.runner = self.batch.runner
        self.batch.jobFinished.connect(self.batch_finished)
        self.queue = self.batch.pending
        self.pdf_window = None
        self.active = None
        self.cards = []
        self.workbench = None
        self.instance = InstanceServer(self) if single_instance else None
        if self.instance:
            self.instance.requested.connect(self.received)
        self.tray = QSystemTrayIcon(tray_icon(), application)
        self.tray.setToolTip("BitDeck · drag a file and press Shift")
        context = QMenu()
        context.addAction("Choose files…", self.browse)
        context.addAction("Image editor / batch queue…", self.show_workbench)
        themes = context.addMenu("Themes")
        themes.addAction("Import classic Winamp skin (.wsz)…", self.import_skin)
        themes.addAction("Reset to BitDeck", self.reset_skin)
        enabled = QAction("Drag + Shift enabled", context, checkable=True, checked=True)
        enabled.toggled.connect(lambda value: setattr(self.watcher, "enabled", value))
        context.addAction(enabled)
        context.addAction("Explorer / Send to integration…", self.shell_settings)
        context.addAction("Third-party licenses…", self.show_licenses)
        context.addAction("Cancel pending actions", self.cancel)
        context.addSeparator()
        context.addAction("Quit BitDeck", self.quit)
        self.tray.setContextMenu(context)
        self.tray.activated.connect(lambda reason: self.browse() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()
        application.aboutToQuit.connect(self.shutdown)

    def received(self, files, workbench):
        if files:
            self.show_files(files)
        elif workbench:
            self.show_workbench()
        else:
            self.notify("BITDECK IS RUNNING", "Drag a supported file and press Shift, or double-click the tray icon.")

    def notify(self, title, detail, result=None):
        # Keep a bounded number of cards; newest result remains visible.
        for card in self.cards:
            card.hide()
            card.deleteLater()
        self.cards = [ResultCard(title, detail, result)]
        self.cards[0].popup()

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self.menu, "Choose files for BitDeck", "", "Supported files (*.png *.jpg *.jpeg *.webp *.pdf *.txt *.md *.csv *.tsv *.json *.log *.xml *.html *.yaml *.yml *.ini *.cfg *.toml *.css *.js *.py *.sql *.wsz);;All files (*)")
        if paths:
            self.show_files(paths)

    def show_files(self, paths):
        paths = [str(Path(path).resolve()) for path in paths if Path(path).is_file()]
        families = {category(path) for path in paths}
        if not paths or len(paths) > 50 or len(families) != 1 or None in families:
            self.notify("UNSUPPORTED SELECTION", "Choose 1–50 images, PDFs, or text files from one family, or one classic .wsz skin. Word documents are not supported.")
            return
        self.menu.popup(QCursor.pos(), paths, drag=False)

    def show_workbench(self, paths=None):
        if self.workbench is None or self.workbench.closing:
            if self.workbench:
                self.workbench.deleteLater()
            self.workbench = MainWindow()
        if isinstance(paths, list):
            self.workbench.add_files(paths)
        self.workbench.show()
        self.workbench.raise_()
        self.workbench.activateWindow()

    def show_pdf(self, paths=None):
        if self.pdf_window is None:
            from .pdf_ui import PDFWindow
            self.pdf_window = PDFWindow(self.batch)
        self.pdf_window.show()
        self.pdf_window.raise_()
        if isinstance(paths, list):
            self.pdf_window.add_files(paths)

    def batch_finished(self, request, result):
        self.active = request
        self.finished(result)

    def choose(self, key, paths):
        if not paths:
            return
        if key == "pdf_controls":
            self.show_pdf(paths)
            return
        if key in {"image_controls", "workbench"}:
            self.show_workbench(paths)
            self.workbench.draw_button.setChecked(True)
            self.workbench.toggle_drawing()
            if key == "image_controls":
                self.workbench.show_tools()
            return
        requests = []
        if key == "import_theme":
            if len(paths) != 1:
                self.notify("CHOOSE ONE SKIN", "Apply one classic .wsz skin at a time.")
                return
            requests = [{"operation": "import_theme", "source": paths[0]}]
        elif key.startswith("image:") or key in {"compress_image", "resize_image", "clean_image"}:
            edge, quality = 0, 85
            if key == "resize_image":
                edge, ok = QInputDialog.getInt(self.menu, "Resize copies", "Maximum long edge (pixels):", 1600, 1, 16384)
                if not ok:
                    return
            if key == "compress_image":
                quality, ok = QInputDialog.getInt(self.menu, "Compress copies", "JPEG / WebP quality (PNG uses lossless optimization):", 72, 1, 100)
                if not ok:
                    return
            for path in paths:
                fmt = key.split(":", 1)[1] if key.startswith("image:") else {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[Path(path).suffix.lower()]
                requests.append({"operation": "export", "source": path, "format": fmt, "quality": quality, "long_edge": edge,
                                 "output_dir": str(Path(path).parent / "BitDeck")})
        elif key in {"images_to_pdf", "pdf_merge"}:
            if key == "pdf_merge" and len(paths) < 2:
                additional, _ = QFileDialog.getOpenFileNames(self.menu, "Add PDFs to merge after this one", "", "PDF (*.pdf)")
                paths = paths + [path for path in additional if path not in paths]
                if len(paths) < 2:
                    return
            requests = [{"operation": key, "source": paths[0], "sources": paths}]
        else:
            options = {}
            if key in {"pdf_to_png", "pdf_to_jpeg"}:
                dpi, ok = QInputDialog.getInt(self.menu, "PDF image quality", "Resolution (DPI):", 150, 72, 300)
                if not ok:
                    return
                options["dpi"] = dpi
            elif key == "pdf_rotate":
                degrees, ok = QInputDialog.getItem(self.menu, "Rotate copies", "Clockwise rotation:", ["90", "180", "270"], 0, False)
                if not ok:
                    return
                options["degrees"] = int(degrees)
            elif key == "pdf_protect":
                password, ok = QInputDialog.getText(self.menu, "Protect copies", "Password (8–128 characters):", QLineEdit.Password)
                if not ok:
                    return
                if not 8 <= len(password) <= 128:
                    self.notify("PASSWORD TOO SHORT", "Use 8–128 characters. Nothing was written.")
                    return
                options["password"] = password
            requests = [{"operation": key, "source": path, **options} for path in paths]
        if len(self.queue) + len(requests) > 200:
            self.notify("QUEUE FULL", "Wait for pending actions before adding more (200-job limit).")
            return
        self.batch.submit(requests, show=len(requests) > 1)

    def start_next(self):
        self.batch.start_next()

    def finished(self, result):
        operation = self.active["operation"] if self.active else "action"
        self.active = None
        self.tray.setToolTip("BitDeck · drag a file and press Shift")
        if result["ok"] and operation == "import_theme":
            try:
                self.themes.apply(result["theme"], persist=True)
                self.notify("SKIN APPLIED", f"{self.themes.current['name']}\nClassic colors and header artwork adapted for BitDeck.")
            except (OSError, ValueError) as error:
                self.notify("THEME SETTINGS", str(error))
        elif result["ok"]:
            count = len(result.get("outputs", [result["output"]]))
            detail = f"{count} output file(s) · {human_bytes(result['input_bytes'])} → {human_bytes(result['output_bytes'])}\n{Path(result['output']).name}"
            self.notify("SAVED / " + operation.replace("_", " ").upper(), detail, result)
        else:
            self.notify("ACTION STOPPED", result.get("error", "Could not process this file."))

    def cancel(self):
        self.batch.cancel_all()

    def import_skin(self):
        path, _ = QFileDialog.getOpenFileName(self.menu, "Import a classic Winamp skin", "", "Winamp classic skin (*.wsz)")
        if path:
            self.choose("import_theme", [path])

    def reset_skin(self):
        try:
            self.themes.reset()
            self.notify("DEFAULT THEME", "BitDeck's original colors restored.")
        except OSError:
            self.notify("DEFAULT THEME", "Default restored for this session; settings could not be updated.")

    def show_licenses(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        path = base / "third-party" / "NOTICES.txt"
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.notify("LICENSES", "Original BitDeck code: MIT. Third-party components retain their own licenses. See README and the distribution's notices.")

    def shell_settings(self):
        from .shell import is_installed, install, uninstall
        if sys.platform != "win32":
            self.notify("WINDOWS INTEGRATION", "Explorer integration is available on Windows only.")
            return
        installed = is_installed()
        verb = "Remove" if installed else "Add"
        answer = QMessageBox.question(self.menu, "Explorer integration", f"{verb} BitDeck's per-user Explorer entry and Send to shortcut?\nNo administrator access is needed. On Windows 11, the entry may appear under Show more options.")
        if answer == QMessageBox.Yes:
            try:
                uninstall() if installed else install()
                self.notify("EXPLORER INTEGRATION", f"Integration {'removed' if installed else 'added'}.")
            except (OSError, subprocess.CalledProcessError):
                self.notify("INTEGRATION UNAVAILABLE", "Windows denied the change. No administrator privileges are requested.")

    def quit(self):
        if (self.runner.busy or self.queue) and QMessageBox.question(self.menu, "Quit BitDeck", "Stop pending work and quit? Completed outputs are kept.") != QMessageBox.Yes:
            return
        self.application.quit()

    def shutdown(self):
        self.queue.clear()
        self.watcher.timer.stop()
        self.runner.shutdown()
        self.menu.hide()
        self.tray.hide()
        if self.instance:
            self.instance.close()
        self.batch.hide()
        if self.pdf_window:
            self.pdf_window.close()
        if self.workbench:
            if self.workbench.tools:
                self.workbench.tools.preview_runner.shutdown()
            self.workbench.closing = True
            self.workbench.close()
        for card in self.cards:
            card.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="BitDeck: drag a file, press Shift, drop on an action")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--workbench", action="store_true", help="Open the optional image editor / batch queue")
    parser.add_argument("--quiet", action="store_true", help="Start in the tray without the welcome card")
    args = parser.parse_args(argv)
    application = create_application()
    files = [str(Path(path).resolve()) for path in args.files]
    if handoff(files, args.workbench):
        return 0
    desktop = Desktop(application)
    if not desktop.instance.listening:
        QMessageBox.warning(None, "BitDeck is starting", "Another instance is starting or the local user channel is unavailable. Try again in a moment.")
        desktop.shutdown()
        return 1
    if args.files:
        QTimer.singleShot(0, lambda: desktop.show_files(args.files))
    elif args.workbench:
        QTimer.singleShot(0, desktop.show_workbench)
    elif not args.quiet:
        QTimer.singleShot(0, lambda: desktop.notify("BITDECK IS READY", "Drag an image, PDF or text file in Explorer. Press Shift while dragging, then drop on an action. Tap Shift again for Tools.\n\nDouble-click the tray icon to choose files. The image editor is optional."))
    code = application.exec()
    desktop.shutdown()
    desktop.menu.deleteLater()
    for card in desktop.cards:
        card.deleteLater()
    if desktop.workbench:
        desktop.workbench.deleteLater()
    desktop.tray.deleteLater()
    desktop.deleteLater()
    from PySide6.QtCore import QEvent
    application.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()
    return code
