"""Is the learner actually at the screen?

Used to pause word rotation while the PC is locked, the user is idle, or a
fullscreen app (video, game, presentation) is running. Uses the Win32 API via
ctypes; on other platforms every probe reports "present".
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IDLE_THRESHOLD_S = 5 * 60

LOCKED, FULLSCREEN, AWAY = "locked", "fullscreen", "away"

# SHQueryUserNotificationState results that mean "something is fullscreen".
_QUNS_BUSY, _QUNS_RUNNING_D3D_FULL_SCREEN, _QUNS_PRESENTATION_MODE = 2, 3, 4
_DESKTOP_SWITCHDESKTOP = 0x0100


def away_reason(locked: bool, fullscreen: bool, idle_seconds: float, idle_threshold: float = IDLE_THRESHOLD_S) -> str | None:
    """Pure decision logic: why the learner is not looking, or None if they are."""
    if locked:
        return LOCKED
    if fullscreen:
        return FULLSCREEN
    if idle_seconds >= idle_threshold:
        return AWAY
    return None


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    if sys.platform != "win32":
        return 0.0
    info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # Both values are 32-bit millisecond tick counts; mask handles wrap-around.
    elapsed_ms = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def is_locked() -> bool:
    """When the workstation is locked, the input desktop cannot be opened."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    handle = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not handle:
        return True
    user32.CloseDesktop(handle)
    return False


def is_fullscreen_app_running() -> bool:
    if sys.platform != "win32":
        return False
    state = ctypes.c_int(0)
    try:
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (AttributeError, OSError):
        return False
    if hr != 0:
        return False
    return state.value in (_QUNS_BUSY, _QUNS_RUNNING_D3D_FULL_SCREEN, _QUNS_PRESENTATION_MODE)


def current_away_reason() -> str | None:
    try:
        return away_reason(is_locked(), is_fullscreen_app_running(), idle_seconds())
    except Exception:  # never let a probe failure break the widget
        log.exception("Presence check failed")
        return None
