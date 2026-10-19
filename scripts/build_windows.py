"""Build a single portable, windowless BitDeck.exe with an embedded frozen worker."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "package"
DIST = ROOT / "windows"


def build(*arguments):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--noupx", "--clean",
                    "--paths", str(ROOT), "--specpath", str(WORK), *arguments], cwd=ROOT, check=True)


def notices():
    output = WORK / "third-party"
    output.mkdir(parents=True, exist_ok=True)
    names = ["Pillow", "PySide6-Essentials", "shiboken6", "pypdf", "pypdfium2", "reportlab",
             "cryptography", "cffi", "pycparser", "charset-normalizer", "typing_extensions", "pyinstaller"]
    lines = ["BITDECK THIRD-PARTY NOTICES", "", "Original BitDeck source: MIT; source and build scripts supplied separately.",
             "Python and third-party components retain their own licenses.",
             "Qt for Python includes LGPL/GPL/commercial components; this build uses the LGPL option.",
             "No restriction is imposed on debugging/replacing LGPL components.",
             "Rebuild instructions are in docs/building-windows.md in the source archive.",
             "Python source: https://www.python.org/downloads/source/",
             "Qt/PySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/",
             "Qt source: https://code.qt.io/cgit/qt/", ""]
    for name in names:
        distribution = metadata.distribution(name)
        lines += [f"{name} {distribution.version}", str(distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "See included license files"),
                  *distribution.metadata.get_all("Project-URL", []), ""]
        for item in distribution.files or []:
            if any(word in str(item).lower() for word in ("license", "copying", "notice", "copyright")):
                source = distribution.locate_file(item)
                if source.is_file() and source.suffix.lower() not in {".dll", ".exe", ".pyd", ".pyc"}:
                    target = output / name / str(item).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, output / "PYTHON-LICENSE.txt")
    shutil.copy2(ROOT / "LICENSE", output / "BITDECK-LICENSE.txt")
    (output / "NOTICES.txt").write_text("\n".join(lines), encoding="utf-8")
    return output


def main():
    global DIST
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-only", action="store_true", help="Reuse an already-built worker after UI-only edits")
    parser.add_argument("--output-dir", type=Path, default=DIST, help="Destination folder; useful when an older EXE is running")
    options = parser.parse_args()
    DIST = options.output_dir.resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    temp = WORK / "temp"
    temp.mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temp)
    # Do not let DLLs from unrelated developer tools (Poppler/libheif/etc.) get
    # discovered and bundled as Windows CRT dependencies.
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(windows / "System32"), str(windows)])
    os.environ.pop("PYTHONPATH", None)
    # Original geometric icon; no Winamp assets are bundled.
    from PIL import Image, ImageDraw
    icon = Image.new("RGB", (256, 256), "#252930")
    draw = ImageDraw.Draw(icon)
    for x, height in [(40, 80), (88, 176), (136, 128), (184, 208)]:
        draw.rectangle((x, 232 - height, x + 31, 232), fill="#c4ee70")
    icon_path = WORK / "bitdeck.ico"
    icon.save(icon_path, sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    licenses = notices()
    worker = WORK / "worker" / "BitDeck-worker.exe"
    if not options.ui_only:
        build("--onefile", "--console", "--name", "BitDeck-worker", "--distpath", str(WORK / "worker"),
              "--workpath", str(WORK / "worker-build"), "--exclude-module", "PySide6", "--exclude-module", "pytest",
              "--exclude-module", "tkinter", "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
              "--collect-data", "reportlab", str(ROOT / "packaging" / "worker_entry.py"))
    if not worker.is_file():
        raise RuntimeError("Build the worker first (omit --ui-only)")
    import PySide6
    qt_directory = Path(PySide6.__file__).parent
    runtime_flags = []
    # Use a consistent current MSVC runtime from the pinned Qt wheel, including
    # at bundle root where the frozen Python loader resolves runtime DLLs first.
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_codecvt_ids.dll", "concrt140.dll"):
        if (qt_directory / name).is_file():
            runtime_flags += ["--add-binary", f"{qt_directory / name}{os.pathsep}."]
    build("--onefile", "--windowed", "--name", "BitDeck", "--icon", str(icon_path),
          "--distpath", str(DIST), "--workpath", str(WORK / "ui-build"),
          "--add-data", f"{worker}{os.pathsep}.", "--add-data", f"{licenses}{os.pathsep}third-party",
          "--exclude-module", "pytest", "--exclude-module", "tkinter",
          "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
          *runtime_flags, str(ROOT / "packaging" / "ui_entry.py"))
    print(f"Built {DIST / 'BitDeck.exe'}")


if __name__ == "__main__":
    main()
