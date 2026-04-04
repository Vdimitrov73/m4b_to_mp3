# install_shortcut.py
"""
install_shortcut.py

Run once to place a Desktop shortcut that launches inaudible_batch.py
with pythonw (no console window) on Windows.
"""

import os
import sys
import subprocess

try:
    import winreg  # Windows only
except ImportError:  # pragma: no cover
    winreg = None

SHORTCUT_NAME = "M4B to MP3 Batch Converter.lnk"


def _get_desktop() -> str:
    """Return the current user's Desktop path via the registry."""
    if winreg is None:
        return os.path.join(os.path.expanduser("~"), "Desktop")
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return desktop
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def _find_pythonw() -> str:
    """Return path to pythonw.exe next to the current Python interpreter."""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    return sys.executable  # fallback: use python.exe (shows a console)


def create_shortcut():
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "inaudible_batch.py")
    )

    if not os.path.isfile(script_path):
        print(f"ERROR: Cannot find script at {script_path}")
        sys.exit(1)

    desktop = _get_desktop()
    shortcut_path = os.path.join(desktop, SHORTCUT_NAME)
    pythonw = _find_pythonw()
    work_dir = os.path.dirname(script_path)

    # Use Windows Script Host via a temporary .vbs to create the .lnk
    vbs_lines = [
        'Set oWS = WScript.CreateObject("WScript.Shell")',
        'Set oLink = oWS.CreateShortcut("' + shortcut_path + '")',
        'oLink.TargetPath = "' + pythonw + '"',
        'oLink.Arguments = "' + script_path + '"',
        'oLink.WorkingDirectory = "' + work_dir + '"',
        'oLink.Description = "M4B to MP3 Batch Converter"',
        'oLink.Save',
    ]

    vbs = "\n".join(vbs_lines) + "\n"

    temp_dir = os.environ.get("TEMP", work_dir)
    vbs_path = os.path.join(temp_dir, "_make_m4b_converter_shortcut.vbs")
    with open(vbs_path, "w", encoding="utf-8") as fh:
        fh.write(vbs)

    result = subprocess.run(
        ["cscript", "//Nologo", vbs_path], capture_output=True, text=True
    )

    try:
        os.remove(vbs_path)
    except OSError:
        pass

    if result.returncode == 0:
        print(f"Shortcut created:\n {shortcut_path}")
    else:
        print(f"Failed to create shortcut.\n{result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    create_shortcut()