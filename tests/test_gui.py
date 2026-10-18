"""Run the widget integration check in a fresh process, apart from QCoreApplication."""
import os
from pathlib import Path
import subprocess
import sys


def test_gui_export_and_undo_failure():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_ui.py")], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
