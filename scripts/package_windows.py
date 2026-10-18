"""Collect the verified executable, notices and original demo skin for delivery."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "windows"
    executable = output / "BitDeck.exe"
    report = json.loads((output / "packaged-check.json").read_text(encoding="utf-8"))
    if not report.get("ok") or not report.get("frozen"):
        raise RuntimeError("Verify the real packaged executable before delivery")
    checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
    if checksum != report.get("executable_sha256"):
        raise RuntimeError("The executable changed after verification; verify it again")
    (output / "SHA256SUMS.txt").write_text(checksum + "  BitDeck.exe\n", encoding="utf-8")
    notes = ("BitDeck portable Windows x64 prototype\n\n"
             "Double-click BitDeck.exe. Python is bundled; no Python/pip installation needed.\n"
             "Drag a file and press Shift; the tray menu offers file selection and the optional editor.\n"
             "Themes > Import classic Winamp skin (.wsz) applies a skin. Voltage-Blue.wsz is an original MIT demo.\n"
             "This build adapts classic skin colors/header artwork, not Winamp's exact player layout.\n\n"
             "The executable is unsigned. Live Explorer/OLE and shell integration still need desktop validation.\n"
             "Resource limits are not a filesystem/network sandbox.\n"
             "Original source and rebuild instructions are in the accompanying BitDeck source archive.\n")
    with zipfile.ZipFile(output / "BitDeck-Windows.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, "BitDeck.exe")
        archive.write(ROOT / "skins" / "Voltage-Blue.wsz", "Voltage-Blue.wsz")
        archive.write(ROOT / "LICENSE", "LICENSE.txt")
        archive.write(output / "SHA256SUMS.txt", "SHA256SUMS.txt")
        archive.write(output / "packaged-check.json", "packaged-check.json")
        archive.writestr("START-HERE.txt", notes)
        folder = ROOT / "work" / "package" / "third-party"
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, "third-party/" + path.relative_to(folder).as_posix())
    print("Packaged BitDeck-Windows.zip and SHA256SUMS.txt")


if __name__ == "__main__":
    main()
