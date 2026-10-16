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
