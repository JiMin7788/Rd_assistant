"""Win32 window geometry via ctypes (spec 03 §7). Windows only, no pywin32.

DPI awareness must be declared before any rect is read. Without it Windows
lies about coordinates whenever display scaling is not 100%, and every click
in the session lands in the wrong place -- consistently enough that it looks
like a calibration problem rather than a bug.
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass

from .geometry import Rect

__all__ = [
    "set_dpi_awareness",
    "find_window",
    "window_title",
    "client_rect_on_screen",
    "dpi_scale",
    "is_minimized",
    "monitor_info",
    "WindowState",
]

if sys.platform != "win32":  # pragma: no cover - import guard
    raise ImportError("rdom.recorder.window requires Windows")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shcore = ctypes.WinDLL("shcore", use_last_error=True)

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
MONITOR_DEFAULTTONEAREST = 2

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def set_dpi_awareness() -> None:
    """Declare per-monitor DPI awareness v2. Must run before any rect read."""
    try:
        if _user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ):
            return
    except AttributeError:
        pass
    try:  # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE
        _shcore.SetProcessDpiAwareness(2)
    except Exception:  # pragma: no cover
        _user32.SetProcessDPIAware()


def window_title(hwnd: int) -> str:
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_window(title_re: str) -> int:
    """Return the single visible top-level window matching ``title_re``.

    Ambiguity is an error, not a coin flip: two LDPlayer instances open would
    otherwise silently record the wrong one.
    """
    pattern = re.compile(title_re)
    hits: list[tuple[int, str]] = []

    def _cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            title = window_title(hwnd)
            if title and pattern.search(title):
                hits.append((hwnd, title))
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)

    if not hits:
        raise RuntimeError(f"no visible window matching {title_re!r}")
    if len(hits) > 1:
        names = ", ".join(t for _, t in hits)
        raise RuntimeError(f"{len(hits)} windows match {title_re!r}: {names}")
    return hits[0][0]


def client_rect_on_screen(hwnd: int) -> Rect:
    """Client area in absolute screen pixels (title bar and borders excluded)."""
    rc = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rc)):
        raise ctypes.WinError(ctypes.get_last_error())
    origin = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())
    return Rect(
        left=origin.x,
        top=origin.y,
        right=origin.x + rc.right,
        bottom=origin.y + rc.bottom,
    )


def dpi_scale(hwnd: int) -> float:
    try:
        return _user32.GetDpiForWindow(hwnd) / 96.0
    except AttributeError:  # pragma: no cover - pre Win10 1607
        return 1.0


def is_minimized(hwnd: int) -> bool:
    return bool(_user32.IsIconic(hwnd))


def monitor_info(hwnd: int) -> dict:
    hmon = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = _MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
    _user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    r = mi.rcMonitor
    return {
        "device": mi.szDevice,
        "rect": [r.left, r.top, r.right, r.bottom],
        "res": [r.right - r.left, r.bottom - r.top],
        "primary": bool(mi.dwFlags & 1),
    }


@dataclass(frozen=True)
class WindowState:
    """Snapshot of every invariant the watchdog checks (spec §7)."""

    client: Rect
    dpi: float
    minimized: bool
    monitor_rect: tuple[int, int, int, int]

    @classmethod
    def read(cls, hwnd: int) -> "WindowState":
        mi = monitor_info(hwnd)
        return cls(
            client=client_rect_on_screen(hwnd),
            dpi=dpi_scale(hwnd),
            minimized=is_minimized(hwnd),
            monitor_rect=tuple(mi["rect"]),  # type: ignore[arg-type]
        )

    def drift(self, other: "WindowState") -> str | None:
        """Human-readable description of the first broken invariant, if any."""
        if self.client != other.client:
            return f"client rect {self.client.as_tuple()} -> {other.client.as_tuple()}"
        if abs(self.dpi - other.dpi) > 1e-6:
            return f"dpi scale {self.dpi} -> {other.dpi}"
        if self.monitor_rect != other.monitor_rect:
            return f"monitor {self.monitor_rect} -> {other.monitor_rect}"
        if other.minimized:
            return "window minimized"
        return None
