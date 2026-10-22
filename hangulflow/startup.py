"""Optional launch at Windows sign-in, via the per-user Run registry key.

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run is the standard,
no-admin-needed mechanism; Task Manager > Startup apps also shows it there.
The registry itself is the source of truth, so the setting can never drift.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "HangulFlow"


def launch_command() -> str:
    """The command Windows runs at sign-in."""
    if getattr(sys, "frozen", False):  # PyInstaller .exe
        return f'"{sys.executable}"'
    # Development: run with pythonw.exe so no console window appears.
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{interpreter}" "{main_py}"'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY) -> bool:
    """Turn launch-at-sign-in on or off. Returns True on success."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        log.info("Start with Windows %s.", "enabled" if enabled else "disabled")
        return True
    except OSError:
        log.exception("Could not change the Windows startup setting")
        return False
