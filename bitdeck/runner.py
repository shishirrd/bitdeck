"""Qt process controller: bounds execution time and IPC; fail closed on Windows."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from .limits import WindowsJob

MAX_REPLY = 8 * 1024 * 1024


class WorkerRunner(QObject):
    completed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.job_object = None
        self.buffer = bytearray()
        self.failure = None
        self.timer = QTimer(self, singleShot=True, interval=90_000)
        self.timer.timeout.connect(lambda: self.stop("Processing exceeded the 90-second limit."))

    @property
    def busy(self):
        return self.process is not None

    def start(self, request):
        if self.busy:
            raise RuntimeError("Worker is busy")
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode()
        if len(payload) > 128 * 1024:
            self.completed.emit({"ok": False, "error": "Job request is too large."})
            return
        self.buffer = bytearray()
        self.failure = None
        process = self.process = QProcess(self)
        process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process.setProgram(str(executable))
        process.setArguments(["-m", "bitdeck.worker"])

        def started():
            try:
                self.job_object = WindowsJob(process.processId())
            except OSError:
                self.stop("Windows could not apply worker resource limits. Processing stopped.")
                return
            # The worker waits for this request before importing Pillow or parsing.
            process.write(payload)
            process.closeWriteChannel()

        process.started.connect(started)
        process.readyReadStandardOutput.connect(self.read)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self.finish)
        process.errorOccurred.connect(lambda error: self.finish() if error == QProcess.FailedToStart else None)
        self.timer.start()
        process.start()

    def read(self):
        if self.process:
            data = bytes(self.process.readAllStandardOutput())
            if len(self.buffer) + len(data) > MAX_REPLY:
                self.stop("Worker reply exceeded its limit.")
            else:
                self.buffer.extend(data)

    def stop(self, message="Cancelled. A completed output may still exist in the output folder."):
        if self.process:
            self.failure = message
            self.process.kill()

    def finish(self, *_):
        if not self.process:
            return
        self.read()
        process, self.process = self.process, None
        self.timer.stop()
        if self.job_object:
            self.job_object.close()
            self.job_object = None
        try:
            result = json.loads(self.buffer) if not self.failure else {"ok": False, "error": self.failure}
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise ValueError()
        except (ValueError, UnicodeError):
            result = {"ok": False, "error": "Worker stopped unexpectedly (possibly a resource limit)."}
        process.deleteLater()
        self.completed.emit(result)

    def shutdown(self):
        self.timer.stop()
        if self.process:
            self.process.kill()
            self.process.waitForFinished(3000)
        if self.job_object:
            self.job_object.close()
            self.job_object = None
