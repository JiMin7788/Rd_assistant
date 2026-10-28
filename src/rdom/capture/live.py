"""Live one-shot content grab for the bot loop.

Reuses the recorder's window/geometry code to locate the emulator's content
rect (client - chrome), then grabs exactly that region with dxcam and returns it
as an RGB ndarray. The frame therefore covers the game content 1:1, matching the
schema-v2 recording convention that perception.board expects.
"""
from __future__ import annotations
import threading

import numpy as np

from rdom.recorder.config import load_config
from rdom.recorder.geometry import Viewport, fit_chrome
from rdom.recorder.window import (
    WindowState, find_window, monitor_info, place_window, set_dpi_awareness,
)


def _tuple(r):
    return r.as_tuple() if hasattr(r, "as_tuple") else tuple(r)


def rects_cover(content, rects):
    """True if any rect overlaps `content` by a positive area (edge contact is not
    overlap). Rects are (left, top, right, bottom) tuples or Rect, screen pixels."""
    cl, ct, cr, cb = _tuple(content)
    for r in rects:
        l, t, rr, b = _tuple(r)
        if min(cr, rr) - max(cl, l) > 0 and min(cb, b) - max(ct, t) > 0:
            return True
    return False


def windows_above(hwnd):
    """Screen rects of the windows stacked above `hwnd` that can actually hide it.

    AI-NOTE: walks the z-order upward (GW_HWNDPREV). Skipped: invisible, minimised,
    DWM-cloaked (other virtual desktops, suspended UWP), zero-area, click-through
    overlays (LAYERED+TRANSPARENT) and the taskbar -- otherwise an overlay app or
    the taskbar would make the game look covered forever and block all saving."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetWindowLongW.restype = ctypes.c_long
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    GW_HWNDPREV, GWL_EXSTYLE = 3, -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
    DWMWA_CLOAKED = 14
    out = []
    cur = u.GetWindow(hwnd, GW_HWNDPREV)
    while cur:
        h = cur
        cur = u.GetWindow(h, GW_HWNDPREV)
        if not u.IsWindowVisible(h) or u.IsIconic(h):
            continue
        cloaked = ctypes.c_int(0)
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                h, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 \
                and cloaked.value:
            continue
        ex = u.GetWindowLongW(h, GWL_EXSTYLE)
        if ex & WS_EX_LAYERED and ex & WS_EX_TRANSPARENT:
            continue
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, buf, 256)
        if buf.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            continue
        rc = wintypes.RECT()
        if not u.GetWindowRect(h, ctypes.byref(rc)):
            continue
        if rc.right <= rc.left or rc.bottom <= rc.top:
            continue
        out.append((rc.left, rc.top, rc.right, rc.bottom))
    return out


def place_game_window(config="config/recorder.toml"):
    """Move the game window to [target.place] (bot start). Returns True if it
    was moved; the caller should give the game a moment to redraw."""
    import time
    cfg = load_config(config)
    if cfg.target.place is None:
        return False
    set_dpi_awareness()
    moved = place_window(find_window(cfg.target.window_title_re), *cfg.target.place)
    if moved:
        time.sleep(1.0)
    return moved


class LiveGrabber:
    def __init__(self, config="config/recorder.toml", grab_timeout=8.0):
        self.cfg = load_config(config)
        set_dpi_awareness()
        self.hwnd = find_window(self.cfg.target.window_title_re)
        self._cam = None
        self._last = None                      # last captured frame (dxcam dup fallback)
        self._baseline = WindowState.read(self.hwnd)
        self.grab_timeout = grab_timeout

    def _camera(self):
        if self._cam is None:
            import dxcam
            self._cam = dxcam.create(
                output_idx=self.cfg.capture.monitor_index, output_color="RGB")
            if self._cam is None:
                raise RuntimeError("dxcam: no output at index "
                                   f"{self.cfg.capture.monitor_index}")
        return self._cam

    def content_rect(self):
        import ctypes
        if not ctypes.windll.user32.IsWindow(self.hwnd):   # game restarted (new window)
            self.hwnd = find_window(self.cfg.target.window_title_re)
            self._baseline = WindowState.read(self.hwnd)
        state = WindowState.read(self.hwnd)
        vp = Viewport(client=state.client,
                      chrome=fit_chrome(state.client, self.cfg.target.chrome))
        return vp.content, state

    def unobscured(self):
        """True if no other window overlaps the game content (R5). Any error ->
        False (fail closed: unknown means do not save)."""
        try:
            content, _ = self.content_rect()
            return not rects_cover(content, windows_above(self.hwnd))
        except Exception:
            return False

    def window_moved(self):
        """True if the window drifted since construction (invalidates coords)."""
        return self._baseline.drift(WindowState.read(self.hwnd)) is not None

    def _grab_region(self, region):
        """The dxcam retry loop (duplicate-frame suppression yields None).

        The retries are spaced: 30 back-to-back calls finish in a couple of
        milliseconds, well inside one display refresh, so they all report "no
        change" and the caller falls back to the PREVIOUS frame. That stale frame
        is what made the 배속 check read the speed from before its own tap
        (2026-09-27). A short wait per retry costs nothing and yields a fresh one.
        """
        import time as _t
        cam = self._camera()
        for k in range(30):
            frame = cam.grab(region=region)
            if frame is not None:
                return frame
            if k:
                _t.sleep(0.008)                  # ~half a refresh at 60Hz
        return None

    def _grab_watchdog(self, region):
        """Run the capture on a worker thread and give up on it after
        `grab_timeout`. dxcam can block FOREVER when its duplication device is
        lost (window minimised, display/resolution change): the bot then sits
        there, no log line, no error, until someone notices (2026-09-27 -- a run
        stalled mid-battle for minutes). A stuck thread cannot be killed, so the
        camera is abandoned (the thread keeps its reference) and a fresh one is
        built for the retry."""
        box = {}

        def work():
            try:
                box["f"] = self._grab_region(region)
            except BaseException as e:           # noqa: BLE001 - reported to caller
                box["e"] = e

        for _ in range(2):
            t = threading.Thread(target=work, daemon=True)
            t.start()
            t.join(self.grab_timeout)
            if t.is_alive():                     # hung in dxcam -> drop the camera
                print(f"    dxcam hung >{self.grab_timeout}s -- new camera",
                      flush=True)
                self._cam = None                 # the stuck thread keeps the old one
                continue
            if "e" in box:
                raise box.pop("e")
            return box.get("f")
        raise RuntimeError("dxcam hung twice -- capture unusable")

    def grab(self):
        """Return the content region as an HxWx3 RGB uint8 ndarray."""
        content, _ = self.content_rect()
        mon = monitor_info(self.hwnd)
        region = content.translated(-mon["rect"][0], -mon["rect"][1]).as_tuple()
        frame = self._grab_watchdog(region)
        if frame is None:
            # dxcam returns None when the screen has not changed since the last
            # grab (duplicate-frame suppression). For a static board that is not an
            # error -- the last frame is still valid, so return it. Only raise if we
            # never captured anything at all.
            if self._last is not None:
                return self._last
            raise RuntimeError("dxcam returned no frame")
        self._last = np.asarray(frame)
        return self._last

    def close(self):
        if self._cam is not None:
            self._cam.release()
            self._cam = None
