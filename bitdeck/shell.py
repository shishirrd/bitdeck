"""Explicit per-user Explorer integration. No elevated installer or auto-start."""
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KEY = r"Software\Classes\*\shell\BitDeck"


def command():
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}" "%1"'
    windowless = executable.with_name("pythonw.exe")
    if windowless.exists():
        executable = windowless
    # A script path works from Explorer's arbitrary working directory.
    return f'"{executable}" "{ROOT / "run_bitdeck.py"}" "%1"'


def is_installed():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY):
            return True
    except FileNotFoundError:
        return False


def install():
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "BitDeck…")
        winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Single")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command())
    # A native shortcut avoids passing dragged file names through cmd.exe.
    # Setup script is constant; values arrive as data through environment variables.
    executable = Path(sys.executable)
    if executable.with_name("pythonw.exe").exists():
        executable = executable.with_name("pythonw.exe")
    send_to = Path(os.environ["APPDATA"]) / "Microsoft/Windows/SendTo/BitDeck.lnk"
    arguments = "" if getattr(sys, "frozen", False) else f'"{ROOT / "run_bitdeck.py"}"'
    working = executable.parent if getattr(sys, "frozen", False) else ROOT
    environment = dict(os.environ, BITDECK_SHORTCUT=str(send_to), BITDECK_PYTHON=str(executable),
                       BITDECK_ARGS=arguments, BITDECK_ROOT=str(working))
    script = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:BITDECK_SHORTCUT); $s.TargetPath = $env:BITDECK_PYTHON; $s.Arguments = $env:BITDECK_ARGS; $s.WorkingDirectory = $env:BITDECK_ROOT; $s.Save()"
    powershell = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                   env=environment, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def uninstall():
    import winreg
    for subkey in (KEY + r"\command", KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass
    send_to = Path(os.environ["APPDATA"]) / "Microsoft/Windows/SendTo/BitDeck.lnk"
    send_to.unlink(missing_ok=True)
