# Building the portable Windows executable

End users run `BitDeck.exe`; they do **not** install Python, pip, Qt or PDF tools.
Python 3.10+ is only a developer/build prerequisite. The portable executable
bundles the UI, Python runtime, dependencies, third-party notices, and a separate
frozen worker executable. It extracts its private runtime to Windows temporary
storage and runs without administrator privileges.

From a source checkout on Windows x64:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev-lock.txt
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build-lock.txt
.\.venv\Scripts\python.exe scripts/build_windows.py
.\.venv\Scripts\python.exe scripts/verify_windows.py
```

The output is `windows/BitDeck.exe`. `verify_windows.py` strips Python/developer
tools from PATH, clears Python-related environment variables, then runs the real
executable through its embedded worker and writes `windows/packaged-check.json`.
It checks images, text/PDF conversion, rendering, text extraction, merge/split,
encryption, .wsz parsing, theme application and reset. It also captures a Qt
preview. This is a packaged runtime check, not proof of an OS without any Python
installation or of live Explorer drag behavior.

The build uses two internal executables because a windowless UI has no normal
console streams. The embedded console worker receives private QProcess pipes;
users download and launch only the outer, windowless `BitDeck.exe`. Windows Job
Object limits still apply to worker processes. No external Python is launched.

For UI-only edits, `--ui-only` reuses an existing worker. If processing, parsers
or worker code changes, omit it to rebuild both. To build alongside an EXE that
Windows has locked because it is running, use a separate output directory:

```powershell
.\.venv\Scripts\python.exe scripts/build_windows.py --ui-only --output-dir windows/updated
.\.venv\Scripts\python.exe scripts/verify_windows.py --executable windows/updated/BitDeck.exe
.\.venv\Scripts\python.exe scripts/package_windows.py --directory windows/updated
```

Quit the older app from its tray menu before launching the replacement. A second
instance hands off to the running copy, so leaving an old copy open keeps its UI.

The `packaging/` entries,
`scripts/build_windows.py`, lock files and full original application source are
provided so users can rebuild, debug or replace components. Third-party libraries
retain their respective licenses; sources/project locations and license texts
are collected in the distribution's third-party notices. LGPL components can be
replaced/rebuilt using these scripts and modified dependency wheels; no application
license restriction prevents doing so. An exact-byte reproducible build is not
claimed. Original theme artwork is MIT; user-supplied skins retain their licenses.

The current executable is an **unsigned prototype**, not a signed installer.
Native Explorer drag behavior, shell registrations and ACL behavior of the local
instance channel still require a normal Windows desktop validation pass.
