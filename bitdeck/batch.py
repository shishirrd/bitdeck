"""Session job history and a sequential, cancellable processing queue."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar, QMessageBox, QDialog, QPlainTextEdit
from .app import button, label
from .runner import WorkerRunner


class BatchWindow(QWidget):
    jobFinished = Signal(dict, dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BitDeck · batch queue")
        self.resize(950, 460)
        self.records = []
        self.pending = []
        self.active = None
        self.paused = False
        self.runner = WorkerRunner(self)
        self.runner.completed.connect(self.finished)
        layout = QVBoxLayout(self)
        layout.addWidget(label("BITDECK  /  BATCH QUEUE", "display"))
        self.summary = label("No jobs yet. Settings are captured when each job is queued.")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["SOURCE", "ACTION", "STATE", "RESULT"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.pause_button = button("PAUSE", self.pause, "Pause between files; the current job finishes")
        row.addWidget(self.pause_button)
        row.addWidget(button("CANCEL SELECTED", self.cancel_selected, "Stop selected running or pending jobs"))
        row.addWidget(button("CANCEL ALL", self.cancel_all, "Stop active and pending jobs; completed outputs are kept"))
        row.addWidget(button("RETRY FAILED", self.retry, "Retry failed or cancelled jobs with their captured settings"))
        row.addWidget(button("OPEN FOLDER", self.open_folder, "Open the selected job's output folder"))
        layout.addLayout(row)
        history = QHBoxLayout()
        history.addWidget(button("JOB DETAILS", self.details, "Review captured settings and results; passwords are hidden"))
        history.addWidget(button("CLEAR FINISHED", self.clear_finished, "Remove finished jobs from this session's history; keep all output files"))
        history.addStretch()
        layout.addLayout(history)

    def submit(self, requests, show=True):
        if len(self.records) + len(requests) > 200:
            QMessageBox.information(self, "Session full", "The session supports 200 jobs. Clear finished history before adding more.")
            return False
        for request in deepcopy(requests):
            if any(request.get(key) for key in ("password", "input_password", "input_passwords")):
                request["requires_password"] = True
            self.records.append({"request": request, "state": "QUEUED", "result": {}})
            self.pending.append(request)
        if show:
            self.show()
            self.raise_()
        self.refresh()
        self.start_next()
        return True

    def start_next(self):
        if self.paused or self.runner.busy or not self.pending:
            return
        request = self.pending.pop(0)
        self.active = next(row for row in self.records if row["request"] is request)
        self.active["state"] = "WORKING"
        self.refresh()
        self.runner.start(request)

    def finished(self, result):
        if self.active is None:
            return
        record, self.active = self.active, None
        record["result"] = result
        record["state"] = "DONE" if result["ok"] else "CANCELLED" if result.get("error", "").startswith("Cancelled") else "FAILED"
        # Passwords remain available for pending jobs only, never in history.
        request = record["request"]
        self.jobFinished.emit(request, result)
        for key in ("password", "input_password", "input_passwords"):
            request.pop(key, None)
        self.refresh()
        QTimer.singleShot(0, self.start_next)

    def refresh(self):
        self.table.setRowCount(len(self.records))
        for index, row in enumerate(self.records):
            result = row["result"]
            detail = result.get("error", result.get("output", ""))
            for column, text in enumerate((Path(row["request"].get("source", "")).name, row["request"]["operation"], row["state"], detail)):
                self.table.setItem(index, column, QTableWidgetItem(text))
        finished = sum(row["state"] in {"DONE", "FAILED", "CANCELLED"} for row in self.records)
        failed = sum(row["state"] == "FAILED" for row in self.records)
        self.summary.setText(f"{finished}/{len(self.records)} finished · {failed} failed · {len(self.pending)} pending · {'Paused' if self.paused else 'Running' if self.runner.busy else 'Ready'}")
        self.progress.setRange(0, max(1, len(self.records)))
        self.progress.setValue(finished)

    def pause(self):
        self.paused = not self.paused
        self.pause_button.setText("RESUME" if self.paused else "PAUSE")
        self.refresh()
        self.start_next()

    def cancel_selected(self):
        for index in {item.row() for item in self.table.selectedItems()}:
            row = self.records[index]
            if row["state"] == "QUEUED":
                self.pending[:] = [request for request in self.pending if request is not row["request"]]
                row["state"] = "CANCELLED"
                for key in ("password", "input_password", "input_passwords"):
                    row["request"].pop(key, None)
            elif row is self.active:
                self.runner.stop()
        self.refresh()

    def cancel_all(self):
        self.pending.clear()
        for row in self.records:
            if row["state"] == "QUEUED":
                row["state"] = "CANCELLED"
                for key in ("password", "input_password", "input_passwords"):
                    row["request"].pop(key, None)
        self.runner.stop()
        self.refresh()

    def retry(self):
        for row in self.records:
            if row["state"] in {"FAILED", "CANCELLED"}:
                if row["request"]["operation"] == "pdf_protect" or row["request"].get("requires_password"):
                    row["result"] = {"error": "Requeue from PDF controls to enter passwords again."}
                    continue
                row["state"], row["result"] = "QUEUED", {}
                self.pending.append(row["request"])
        self.refresh()
        self.start_next()

    def open_folder(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.records):
            output = self.records[index]["result"].get("output")
            if output:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output).parent)))

    def clear_finished(self):
        self.records[:] = [row for row in self.records if row["state"] in {"WORKING", "QUEUED"}]
        self.refresh()

    def details(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.records):
            import json
            row = self.records[index]
            request = {k: v for k, v in row["request"].items() if k not in {"password", "input_password", "input_passwords"}}
            dialog = QDialog(self)
            dialog.setWindowTitle("Job settings and result")
            dialog.resize(650, 450)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(json.dumps({"request": request, "state": row["state"], "result": row["result"]}, indent=2))
            layout.addWidget(text)
            layout.addWidget(button("CLOSE", dialog.accept, "Return to the queue"))
            dialog.exec()

    def closeEvent(self, event):
        # Closing the monitor does not interrupt processing in the tray app.
        event.accept()
