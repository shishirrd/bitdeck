"""Regenerate Windows x64 wheel hashes from PyPI metadata. Review changes."""
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = {"Pillow": "12.3.0", "PySide6-Essentials": "6.12.0", "shiboken6": "6.12.0"}
DEV = {"pytest": "9.1.1", "colorama": "0.4.6", "exceptiongroup": "1.3.1",
       "iniconfig": "2.3.1", "packaging": "26.3", "pluggy": "1.7.0",
       "Pygments": "2.21.0", "tomli": "2.5.0", "typing_extensions": "4.16.0"}


def requirement(name, version):
    with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        metadata = json.load(response)
    wheels = [item for item in metadata["urls"] if item["filename"].endswith(".whl") and
              ("win_amd64" in item["filename"] or "none-any" in item["filename"])]
    if not wheels:
        raise RuntimeError(f"No Windows x64 / universal wheels found: {name}")
    hashes = sorted({item["digests"]["sha256"] for item in wheels})
    return f"{name}=={version}" + "".join(f" \\\n    --hash=sha256:{value}" for value in hashes) + "\n"


if __name__ == "__main__":
    runtime = "# Windows x64; generated from PyPI wheel metadata.\n--require-hashes\n" + "".join(requirement(name, version) for name, version in RUNTIME.items())
    (ROOT / "requirements-lock.txt").write_text(runtime, encoding="utf-8")
    development = "# Includes runtime and test dependencies for Python 3.10 on Windows x64.\n-r requirements-lock.txt\n" + "".join(requirement(name, version) for name, version in DEV.items())
    (ROOT / "requirements-dev-lock.txt").write_text(development, encoding="utf-8")
    print("Wrote runtime and development lock files.")
