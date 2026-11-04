"""rdT07: Injector activation + cross-process lock (fake user32/kernel32, nothing is posted),
single-instance refusal, friend-list multi-threshold OCR."""
import importlib
import importlib.util
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from rdom.input import friend_coop, inject
from rdom.input.inject import Injector

ROOT = Path(__file__).resolve().parents[1]
TOP, RENDER = 11, 22


class World:
    def __init__(self, wait=0, post_raises=False):
        self.log, self.fg, self.wait, self.post_raises = [], 7, wait, post_raises   # another window in front
        self.fg_after_set = TOP
        self.activation_works = True
        u = types.SimpleNamespace()
        u.IsWindow = lambda h: True
        u.MapVirtualKeyW = lambda k, t: 1
        u.GetForegroundWindow = lambda: self.fg
        u.SendMessageW = self._send
        u.PostMessageW = self._post
        u.SetForegroundWindow = self._setfg
        u.BringWindowToTop = lambda h: self.log.append(("top", h))
        u.GetWindowThreadProcessId = lambda h, p: 5
        u.AttachThreadInput = lambda a, b, on: self.log.append(("attach", on)) or 1
        u.keybd_event = lambda vk, sc, fl, ex: self.log.append(("alt", fl))
        self.user32 = u
        k = types.SimpleNamespace()
        k.CreateMutexW = lambda a, b, name: self.log.append(("mutex", name)) or 99
        k.WaitForSingleObject = lambda h, ms: self.log.append(("wait",)) or self.wait
        k.GetCurrentThreadId = lambda: 4
        k.ReleaseMutex = lambda h: self.log.append(("release",)) or 1
        self.kernel32 = k

    def _send(self, h, msg, w, l):
        self.log.append(("send", h, msg, w))
        if msg == inject.WM_ACTIVATE and self.activation_works:
            self.fg = TOP

    def _setfg(self, h):
        self.log.append(("setfg", h))
        self.fg = self.fg_after_set

    def _post(self, h, msg, w, l):
        if self.post_raises:
            raise OSError("boom")
        self.log.append(("post", h, msg))
        return 1

    def kinds(self):
        return [e[0] for e in self.log]


def make(monkeypatch, world, execute=True):
    monkeypatch.setattr(inject, "_user32", world.user32)
    monkeypatch.setattr(inject, "_kernel32", world.kernel32)
    monkeypatch.setattr(inject.time, "sleep", lambda s: None)
    inj = Injector(execute=False, config=str(ROOT / "config" / "recorder.toml"))
    inj.execute, inj._top, inj._render = execute, TOP, RENDER
    monkeypatch.setattr(inj, "_point", lambda u, v, jitter=4: (5, 6))
    return inj


ACTIVATION = [("send", TOP, inject.WM_ACTIVATEAPP, 1), ("send", TOP, inject.WM_NCACTIVATE, 1),
              ("send", TOP, inject.WM_ACTIVATE, 1), ("send", RENDER, inject.WM_SETFOCUS, 0)]


def test_tap_locks_activates_posts_releases_in_order(monkeypatch):
    w = World()
    inj = make(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert w.log[:6] == [("mutex", "Local\\rdom_input"), ("wait",)] + ACTIVATION
    assert w.kinds()[6:] == ["post", "post", "post", "release"]


def test_swipe_holds_the_lock_for_the_whole_drag(monkeypatch):
    w = World()
    inj = make(monkeypatch, w)
    inj.swipe(0.1, 0.1, 0.5, 0.5, dur_ms=200)
    k = w.kinds()
    assert k[:2] == ["mutex", "wait"] and k[2:6] == ["send"] * 4
    assert k.count("release") == 1 and k[-1] == "release" and k.count("post") >= 8
    assert k.index("post") > 5


def test_back_locks_and_activates(monkeypatch):
    w = World()
    inj = make(monkeypatch, w)
    inj.back()
    assert w.log[2:6] == ACTIVATION and w.kinds()[-3:] == ["post", "post", "release"]


@pytest.mark.parametrize("gesture", ["tap", "swipe"])
def test_lock_released_when_posting_raises(monkeypatch, gesture):
    w = World(post_raises=True)
    inj = make(monkeypatch, w)
    with pytest.raises(OSError):
        if gesture == "tap":
            inj.tap(0.5, 0.5)
        else:
            inj.swipe(0.1, 0.1, 0.5, 0.5)
    assert w.kinds().count("release") == 1


def test_dry_run_does_no_activation_and_no_lock(monkeypatch, capsys):
    w = World()
    inj = make(monkeypatch, w, execute=False)
    inj.tap(0.5, 0.5)
    inj.swipe(0.1, 0.1, 0.2, 0.2)
    inj.back()
    assert w.log == []
    assert "[dry-run] tap" in capsys.readouterr().out


def test_lock_timeout_skips_the_gesture(monkeypatch, capsys):
    w = World(wait=0x102)
    inj = make(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert not {"post", "release", "send"} & set(w.kinds())
    assert "input lock timeout" in capsys.readouterr().out


# ---- rdT10: activation timing, last_gesture_ok, counters, fair yield
class Clock:
    """Fake inject.time: sleep advances the clock and records the pause."""
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_clock(monkeypatch, world):
    inj = make(monkeypatch, world)
    clk = Clock()
    monkeypatch.setattr(inject, "time", clk)
    return inj, clk


def test_already_foreground_no_delay_no_switch(monkeypatch):
    w = World()
    w.fg = TOP
    inj, clk = make_clock(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert "send" not in w.kinds() and inject.ACTIVATE_SETTLE_S not in clk.sleeps
    assert inj.last_gesture_ok is True and inj.stats["switches"] == 0 and inj.stats["gestures"] == 1


def test_switch_polls_then_settles_before_first_post(monkeypatch):
    w = World()
    w.activation_works, w.fg_after_set = False, 7
    inj, clk = make_clock(monkeypatch, w)
    calls = []
    def fg():
        calls.append(1)
        if len(calls) > 8:
            w.fg = TOP                       # becomes foreground only after a few polls
        return w.fg
    w.user32.GetForegroundWindow = fg
    inj.tap(0.5, 0.5)
    assert inject.FG_POLL_S in clk.sleeps and inject.ACTIVATE_SETTLE_S in clk.sleeps
    assert clk.sleeps.index(inject.ACTIVATE_SETTLE_S) > clk.sleeps.index(inject.FG_POLL_S)
    assert inj.last_gesture_ok is True and inj.stats["switches"] == 1 and inj.stats["not_foreground"] == 0
    assert w.kinds().count("post") == 3


def test_force_path_only_when_messages_did_not_work(monkeypatch):
    w = World()                              # messages make it foreground
    inj, clk = make_clock(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert not {"alt", "attach", "setfg", "top"} & set(w.kinds())
    w2 = World()
    w2.activation_works = False              # only SetForegroundWindow works
    inj2, clk2 = make_clock(monkeypatch, w2)
    inj2.tap(0.5, 0.5)
    k = w2.kinds()
    assert k.count("attach") == 2 and k.count("alt") == 2 and "setfg" in k and "top" in k
    assert w2.log[k.index("attach")] == ("attach", True) and inj2.last_gesture_ok is True


def test_never_foreground_posts_anyway_flags_not_ok_and_warns_once_per_60s(monkeypatch, capsys):
    w = World()
    w.activation_works, w.fg_after_set = False, 7
    inj, clk = make_clock(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert inj.last_gesture_ok is False and w.kinds().count("post") == 3
    assert inject.ACTIVATE_SETTLE_S not in clk.sleeps and sum(clk.sleeps) >= inject.FG_POLL_MAX_S
    inj.tap(0.5, 0.5)
    assert capsys.readouterr().out.count("did not become the foreground") == 1
    clk.t += inject.FG_WARN_EVERY_S
    inj.tap(0.5, 0.5)
    assert capsys.readouterr().out.count("did not become the foreground") == 1
    assert inj.stats["not_foreground"] == 3 and inj.stats["gestures"] == 3


def test_lock_timeout_counted_and_not_ok(monkeypatch):
    w = World(wait=0x102)
    inj, clk = make_clock(monkeypatch, w)
    inj.tap(0.5, 0.5)
    assert inj.last_gesture_ok is False and inj.stats["lock_timeouts"] == 1


def test_lock_release_yields_to_the_waiting_bot(monkeypatch):
    w = World()
    inj, clk = make_clock(monkeypatch, w)
    order = []
    w.kernel32.ReleaseMutex = lambda h: order.append("release") or 1
    orig = clk.sleep
    clk.sleep = lambda s: (order.append(("sleep", s)), orig(s))
    inj.tap(0.5, 0.5)
    i = order.index("release")
    assert order[i + 1] == ("sleep", inject.LOCK_YIELD_S) and i + 2 == len(order)


def test_gear_loop_input_stats_line(capsys):
    spec = importlib.util.spec_from_file_location("gear_loop_t10", ROOT / "tools" / "gear_loop.py")
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(str(ROOT / "tools"))
    inj = types.SimpleNamespace(stats={"gestures": 9, "switches": 4, "not_foreground": 1, "lock_timeouts": 2})
    m.log_input_stats(inj)
    assert "input: 9 gestures, 4 switches, 1 not in front, 2 lock timeouts" in capsys.readouterr().out
    assert inj.stats["gestures"] == 0


# ---- single instance
def test_run_all_refuses_second_copy(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("run_all_t7", ROOT / "tools" / "run_all.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lock = tmp_path / "run_all.pid"
    lock.write_text("424242")
    monkeypatch.setattr(m, "LOCK", str(lock))
    monkeypatch.setattr(m, "alive", lambda p: True)
    monkeypatch.setattr(m, "SECOND_COPY_WAIT_S", 0)
    monkeypatch.setattr(m, "start", lambda *a, **k: pytest.fail("started a process"))
    assert m.main([]) != 0
    assert "이미 실행 중이에요 -- 두 번째 실행은 무시합니다" in capsys.readouterr().out
    assert lock.read_text() == "424242"


def _sup(monkeypatch):
    for n in ("tools.supervisor", "supervisor"):
        monkeypatch.delitem(sys.modules, n, raising=False)
    mod = importlib.import_module("tools.supervisor")
    sys.modules.pop("tools.supervisor", None)
    return mod


def test_supervisor_refuses_second_copy(monkeypatch, tmp_path, capsys):
    sup = _sup(monkeypatch)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "supervisor.pid").write_text("424242")
    fake = types.SimpleNamespace(pid_exists=lambda p: True,
                                 Process=lambda p: types.SimpleNamespace(name=lambda: "python.exe"))
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr(sup, "ROOT", str(tmp_path))
    monkeypatch.setattr(sup, "Supervisor", lambda *a: pytest.fail("started bots"))
    assert sup.main(["--mode", "duo"]) != 0
    assert "이미 실행 중이에요 -- 두 번째 실행은 무시합니다" in capsys.readouterr().out


def test_supervisor_own_or_missing_pid_file_is_not_a_second_copy(monkeypatch, tmp_path):
    sup = _sup(monkeypatch)
    p = tmp_path / "supervisor.pid"
    p.write_text(str(os.getpid()))
    assert sup.running_supervisor(str(p)) is None
    assert sup.running_supervisor(str(tmp_path / "none")) is None


# ---- friend list OCR
def _frame():
    return np.zeros((20, 20, 3), np.uint8)


def test_friend_found_when_only_one_threshold_reads_the_name(monkeypatch, tmp_path):
    monkeypatch.setattr(friend_coop, "COOP_DEBUG_DIR", str(tmp_path / "cd"))
    seen = []

    def ocr(f, region, scale=3, thresh=None):
        seen.append(thresh)
        if thresh == 120:
            return [("배", 0.3, 0.4), ("속", 0.35, 0.4), ("봇", 0.4, 0.4)]
        return [("zzz", 0.3, 0.5)]
    monkeypatch.setattr(friend_coop, "_ocr_data", ocr)
    assert friend_coop.find_friend_in_popup(_frame(), "배속봇") == (0.5, 0.4)
    assert seen[:2] == [150, 120] and not (tmp_path / "cd").exists()


def test_friend_not_found_saves_frame_and_keeps_20(monkeypatch, tmp_path, capsys):
    d = tmp_path / "cd"
    d.mkdir()
    for i in range(25):
        f = d / f"friend_list_old{i:02d}.png"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))
    monkeypatch.setattr(friend_coop, "COOP_DEBUG_DIR", str(d))
    monkeypatch.setattr(friend_coop, "_ocr_data", lambda *a, **k: [])
    assert friend_coop.find_friend_in_popup(_frame(), "배속봇") is None
    files = list(d.glob("friend_list_*.png"))
    assert len(files) == 20 and any(not f.name.startswith("friend_list_old") for f in files)
    assert "friend list saved:" in capsys.readouterr().out
