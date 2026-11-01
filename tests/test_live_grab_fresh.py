import threading
import time

import numpy as np
import pytest

from rdom.capture import live
from rdom.capture.live import LiveGrabber
from rdom.recorder.geometry import Rect


class FakeCam:
    def __init__(self, frames):
        self.frames = list(frames)
        self.regions = []

    def grab(self, region=None):
        self.regions.append(region)
        return self.frames.pop(0) if self.frames else None


def make(cam, monkeypatch, content=(2020, 50, 2420, 850), mon=(1920, 0)):
    g = LiveGrabber.__new__(LiveGrabber)
    g.hwnd = 1
    g._cam = cam
    g._last = None
    g.grab_timeout = 0.2
    g.content_rect = lambda: (Rect(*content), None)
    monkeypatch.setattr(live, "monitor_info", lambda hwnd: {"rect": (mon[0], mon[1], 0, 0)})
    g._camera = lambda: cam          # also after a watchdog rebuild (no dxcam here)
    return g


def test_region_uv_to_monitor_pixels(monkeypatch):
    cam = FakeCam([np.zeros((10, 10, 3), np.uint8)])
    g = make(cam, monkeypatch)       # content 400x800 at monitor-relative (100, 50)
    g.grab_fresh((0.25, 0.5, 0.75, 0.625))
    assert cam.regions[0] == (200, 450, 400, 550)


def test_no_region_is_whole_content(monkeypatch):
    cam = FakeCam([np.zeros((2, 2, 3), np.uint8)])
    g = make(cam, monkeypatch)
    g.grab_fresh()
    assert cam.regions[0] == (100, 50, 500, 850)


def test_none_returns_none_not_last(monkeypatch):
    cam = FakeCam([])
    g = make(cam, monkeypatch)
    g._last = np.ones((2, 2, 3), np.uint8)
    t0 = time.perf_counter()
    frame, t = g.grab_fresh(retry_sleep=0.0005)
    assert frame is None and t >= t0
    assert len(cam.regions) > 5


def test_timestamp_after_frame_arrives(monkeypatch):
    stamps = {}

    class SlowCam(FakeCam):
        def grab(self, region=None):
            time.sleep(0.03)
            stamps["ret"] = time.perf_counter()
            return np.zeros((2, 2, 3), np.uint8)

    g = make(SlowCam([]), monkeypatch)
    before = time.perf_counter()
    frame, t = g.grab_fresh()
    assert frame is not None
    assert t >= stamps["ret"] >= before + 0.03
    assert t - stamps["ret"] < 0.02


def test_grab_still_falls_back_to_last(monkeypatch):
    cam = FakeCam([])
    g = make(cam, monkeypatch)
    g._last = np.full((2, 2, 3), 7, np.uint8)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert g.grab() is g._last
    assert len(cam.regions) == 30


def test_grab_region_default_spacing(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    g = make(FakeCam([]), monkeypatch)
    assert g._grab_region((0, 0, 1, 1)) is None
    assert set(sleeps) == {0.008} and len(sleeps) == 29


def test_hung_camera_hits_watchdog(monkeypatch):
    release = threading.Event()

    class HungCam:
        def grab(self, region=None):
            release.wait(5)

    g = make(HungCam(), monkeypatch)
    g.grab_timeout = 0.05
    calls = []
    orig = g._grab_watchdog
    g._grab_watchdog = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
    try:
        with pytest.raises(RuntimeError, match="hung twice"):
            g.grab_fresh()
    finally:
        release.set()
    assert calls == [1]
