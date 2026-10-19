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


def test_cursor_menu_drop_pipeline():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_desktop.py")], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_wsz_import_apply_reload_and_reset():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_theme.py")], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_image_pdf_controls_and_batch_queue():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_editing.py")], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr


def test_radial_motion_and_modeless_action_flow():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_motion.py")], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
