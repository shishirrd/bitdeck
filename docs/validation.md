# Local validation

18 October 2026. Windows x64, Python 3.10.11, Pillow 12.3.0,
PySide6 Essentials / shiboken6 6.12.0.

The regression suite contains 24 checks. A separate clean environment installs
only the hash-locked runtime and test dependencies, excluding optional Qt modules.

Validation includes real child-process inspection and encoding, Windows Job
Object assignment/termination and memory enforcement, concurrent publication,
changed-source rejection, and a Qt widget integration check that exercises
preview, export, resizing, redaction and failed Undo without using the user's
actual Recycle Bin. `scripts/smoke_ui.py` regenerates the screenshot using an
original procedural test image and the actual running interface.

In this restricted development environment, tests use a workspace temporary
directory because publication operations in the environment-owned temporary
directory are denied. Run:

```powershell
New-Item -ItemType Directory -Force work | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp=work/test-data
```

The public PyPI advisory service via pip-audit 2.10.1 reported no known
vulnerabilities for the three exact runtime package versions at review time.
The machine-readable result is [dependency-audit.json](dependency-audit.json).
This is a Python-package advisory check, not a complete audit of Qt's bundled
native libraries, and does not prove the packages free of vulnerabilities.

The dependency locks pin versions and Windows x64 wheel hashes. CI actions are
pinned to commit IDs. There are no signed or packaged executable releases yet.
GitHub-hosted CI has not run until the repository is published.
