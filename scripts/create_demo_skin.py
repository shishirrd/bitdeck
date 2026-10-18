"""Create original MIT-licensed .wsz artwork for testing BitDeck's importer."""
import io
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "skins"
    folder.mkdir(exist_ok=True)
    bitmap = Image.new("RGB", (275, 116), (28, 47, 88))
    draw = ImageDraw.Draw(bitmap)
    draw.rectangle((0, 0, 274, 13), fill="#384f84")
    for x in range(4, 275, 8):
        draw.line((x, 1, x, 12), fill="#7292ce")
    draw.rectangle((47, 26, 252, 63), fill="#080c14")
    draw.rectangle((15, 81, 261, 105), outline="#7292ce")
    buffer = io.BytesIO()
    bitmap.save(buffer, "BMP")
    path = folder / "Voltage-Blue.wsz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in {"MAIN.BMP": buffer.getvalue(),
                            "PLEDIT.TXT": b"[Text]\nNormal=#4dd0ff\nNormalBG=#080c14\nCurrent=#ffe38a\nSelectedBG=#1c2f58\n",
                            "README.txt": b"Voltage Blue: original BitDeck demonstration artwork, MIT licensed. No Winamp artwork copied.\n"}.items():
            member = zipfile.ZipInfo(name, date_time=(2026, 10, 18, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, value)
    print(path)


if __name__ == "__main__":
    main()
