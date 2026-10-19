"""Verify the real portable .exe without Python or developer tools on PATH."""
import json
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=ROOT / "windows" / "BitDeck.exe")
    executable = parser.parse_args().executable.resolve()
    report = executable.parent / "packaged-check.json"
    report.unlink(missing_ok=True)
    temp = ROOT / "work" / "package" / "verification-temp"
    temp.mkdir(parents=True, exist_ok=True)
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    environment = dict(os.environ, PATH=str(windows / "System32") + os.pathsep + str(windows),
                       TEMP=str(temp), TMP=str(temp), QT_QPA_PLATFORM="offscreen")
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYINSTALLER_RESET_ENVIRONMENT"):
        environment.pop(name, None)
    process = subprocess.run([str(executable), "--self-test", "--report", str(report)],
                             env=environment, cwd=temp, timeout=180, capture_output=True)
    if not report.exists():
        raise RuntimeError(f"Packaged app did not write a report (exit {process.returncode}): {process.stderr[:2000]!r}")
    result = json.loads(report.read_text(encoding="utf-8"))
    if process.returncode or not result.get("ok") or not result.get("frozen"):
        print(json.dumps(result, indent=2))
        print(f"Packaged process exit: {process.returncode}; stderr: {process.stderr[:2000]!r}")
        raise SystemExit(1)
    result["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    result["path_policy"] = "Windows system directories only; Python environment overrides cleared"
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
