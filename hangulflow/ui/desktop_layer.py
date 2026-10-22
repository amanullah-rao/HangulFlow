"""Keep a window on the desktop layer: behind all normal windows (Windows only).

Two parts:
1. WM_WINDOWPOSCHANGING is intercepted so any attempt to raise the widget
   (clicking it, showing it) puts it directly above the desktop instead.
2. A foreground-change hook: when the desktop itself becomes the active
   window (Win+D, "Show desktop", clicking the wallpaper), the widget is
   brought forward so it is visible there; when any other app becomes active,
   it goes back behind everything.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

WM_WINDOWPOSCHANGING = 0x0046
HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
GW_HWNDPREV = 3
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
DESKTOP_CLASSES = {"Progman", "WorkerW"}

_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD
)


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def supported() -> bool:
    return sys.platform == "win32"


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(wintypes.HWND(hwnd), buf, 64)
    return buf.value


def _desktop_window() -> int:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    return user32.FindWindowW("Progman", None) or 0


def _slot_above_desktop(hwnd: int) -> int | None:
    """Window to insert after so we sit directly above the desktop; None if already there."""
    user32 = ctypes.windll.user32
    user32.GetWindow.restype = wintypes.HWND
    desktop = _desktop_window()
    if not desktop:
        return HWND_BOTTOM
    above = user32.GetWindow(wintypes.HWND(desktop), GW_HWNDPREV) or 0
    if above == hwnd:
        return None
    return above or HWND_BOTTOM


def _set_pos(hwnd: int, insert_after: int) -> None:
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(insert_after), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )


class DesktopPin:
    """Pins one window to the desktop layer while enabled."""

    def __init__(self) -> None:
        self._hwnd = 0
        self._hook = None
        self._callback = _WINEVENTPROC(self._on_foreground)  # keep a reference alive
        self._showing_on_desktop = False

    @property
    def active(self) -> bool:
        return bool(self._hwnd)

    def enable(self, hwnd: int) -> None:
        if not supported():
            return
        self._hwnd = hwnd
        if self._hook is None:
            user32 = ctypes.windll.user32
            user32.SetWinEventHook.restype = wintypes.HANDLE
            self._hook = user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._callback, 0, 0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            )
            if not self._hook:
                log.warning("Could not install the foreground hook; Win+D will cover the widget.")
        foreground = ctypes.windll.user32.GetForegroundWindow() or 0
        self._apply(_class_name(foreground) in DESKTOP_CLASSES if foreground else False)

    def disable(self) -> None:
        if self._hook:
            ctypes.windll.user32.UnhookWinEvent(wintypes.HANDLE(self._hook))
            self._hook = None
        if self._hwnd and self._showing_on_desktop:
            _set_pos(self._hwnd, HWND_NOTOPMOST)
        self._hwnd = 0
        self._showing_on_desktop = False

    def filter_native_event(self, message_ptr: int) -> None:
        """Call from QWidget.nativeEvent with the raw MSG pointer."""
        if not self._hwnd or self._showing_on_desktop:
            return
        msg = wintypes.MSG.from_address(message_ptr)
        if msg.message == WM_WINDOWPOSCHANGING and msg.lParam:
            pos = WINDOWPOS.from_address(msg.lParam)
            slot = _slot_above_desktop(self._hwnd)
            if slot is None:
                pos.flags |= SWP_NOZORDER  # already right above the desktop
            else:
                pos.hwndInsertAfter = slot
                pos.flags &= ~SWP_NOZORDER

    def _on_foreground(self, _hook, _event, hwnd, _obj, _child, _thread, _time) -> None:
        try:
            if self._hwnd and hwnd:
                self._apply(_class_name(hwnd) in DESKTOP_CLASSES)
        except Exception:  # an exception must never escape into Windows' callback
            log.exception("Desktop foreground hook failed")

    def _apply(self, desktop_in_front: bool) -> None:
        if desktop_in_front:
            self._showing_on_desktop = True
            _set_pos(self._hwnd, HWND_TOPMOST)  # visible above the "shown" desktop
        else:
            if self._showing_on_desktop:
                self._showing_on_desktop = False
                _set_pos(self._hwnd, HWND_NOTOPMOST)
            slot = _slot_above_desktop(self._hwnd)
            if slot is not None:
                _set_pos(self._hwnd, slot)
