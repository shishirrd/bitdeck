import json
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QProcess

from bitdeck.limits import WindowsJob
from bitdeck.runner import WorkerRunner


def wait_until(app, predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "Timed out waiting for worker"


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_worker_lifecycle_and_limits(app, tmp_path):
    from PIL import Image
    source = tmp_path / "sample.png"
    Image.new("RGB", (50, 30), "red").save(source)
    runner = WorkerRunner()
    results = []
    runner.completed.connect(results.append)
    runner.start({"operation": "export", "source": str(source), "output_dir": str(tmp_path / "out")})
    wait_until(app, lambda: bool(results))
    assert results[0]["ok"], results[0]
    assert runner.job_object is None
    assert not runner.busy


def test_cancel_cleans_process_and_reports_failure(app, tmp_path):
    runner = WorkerRunner()
    results = []
    runner.completed.connect(results.append)
    runner.start({"operation": "inspect", "source": str(tmp_path / "missing.png")})
    runner.stop()
    wait_until(app, lambda: bool(results))
    assert results[0]["ok"] is False
    assert "Cancelled" in results[0]["error"]
    assert not runner.busy


def test_timeout_stops_worker(app, tmp_path):
    runner = WorkerRunner()
    results = []
    runner.completed.connect(results.append)
    runner.timer.setInterval(1)
    runner.start({"operation": "inspect", "source": str(tmp_path / "missing.png")})
    wait_until(app, lambda: bool(results))
    assert results[0]["ok"] is False
    assert "90-second" in results[0]["error"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object")
def test_job_close_terminates_assigned_process(app):
    process = QProcess()
    process.start(sys.executable, ["-c", "import time; time.sleep(60)"])
    assert process.waitForStarted(5000)
    job = WindowsJob(process.processId())
    assert job.handle
    job.close()
    assert process.waitForFinished(5000)
    assert process.state() == QProcess.NotRunning


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object")
def test_windows_memory_budget_is_enforced(app):
    script = """import sys
sys.stdin.buffer.readline()
try:
    blocks = [bytearray(16 * 1024 * 1024) for _ in range(64)]
    print('UNLIMITED', flush=True)
except MemoryError:
    print('LIMITED', flush=True)
"""
    process = QProcess()
    process.start(sys.executable, ["-c", script])
    assert process.waitForStarted(5000)
    job = WindowsJob(process.processId(), memory_mb=128)
    try:
        process.write(b"go\n")
        process.closeWriteChannel()
        assert process.waitForFinished(10000)
        assert bytes(process.readAllStandardOutput()).strip() == b"LIMITED"
    finally:
        job.close()
        if process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(3000)
