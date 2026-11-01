"""press / release / cancel on both backends -- fake PostMessage and fake subprocess only."""
import statistics
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from rdom.input import inject
from rdom.input.inject import (
    PRESS_LEAD_GPG, PRESS_LEAD_LD, AdbInjector, Injector, method_line,
    MK_LBUTTON, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
)

ROOT = Path(__file__).resolve().parents[1]
LD = str(ROOT / "config" / "recorder_ld.toml")
GPG = str(ROOT / "config" / "recorder.toml")

GETEVENT_OK = """add device 1: /dev/input/event1
  name:     "Power Button"
  events:
    KEY (0001): KEY_POWER
add device 2: /dev/input/event2
  name:     "Android_Input"
  events:
    KEY (0001): BTN_TOUCH
    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 1439, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 2559, fuzz 0, flat 0, resolution 0
                ABS_MT_TRACKING_ID    : value 0, min 0, max 65535, fuzz 0, flat 0, resolution 0
"""
GETEVENT_NO_MT = """add device 1: /dev/input/event1
  name:     "Keyboard"
  events:
    KEY (0001): KEY_A
"""


# ---------------------------------------------------------------- GPG (window messages)

class Posts:
    def __init__(self):
        self.msgs = []

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.msgs.append((msg, wparam, lparam & 0xFFFF, (lparam >> 16) & 0xFFFF))
        return 1

    def ScreenToClient(self, hwnd, pt):
        return 1


def _gpg(monkeypatch, execute=True):
    posts = Posts()
    content = SimpleNamespace(left=100, top=50, width=1000, height=2000, right=1100, bottom=2050)
    monkeypatch.setattr(inject, "_user32", posts)
    monkeypatch.setattr(inject.WindowState, "read", staticmethod(lambda top: SimpleNamespace(client=None)))
    monkeypatch.setattr(inject, "fit_chrome", lambda client, chrome: None)
    monkeypatch.setattr(inject, "Viewport", lambda client, chrome: SimpleNamespace(content=content))
    inj = Injector(execute=False, config=GPG)
    inj.execute = execute
    monkeypatch.setattr(inj, "_target", lambda: (1, 2))
    return inj, posts


def test_gpg_dry_run_posts_nothing_and_prints(monkeypatch, capsys):
    inj, posts = _gpg(monkeypatch, execute=False)
    monkeypatch.setattr(inject.subprocess, "run", lambda *a, **k: pytest.fail("subprocess in dry run"))
    inj.press(0.5, 0.5)
    inj.release()
    inj.cancel()
    assert posts.msgs == []
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["    [dry-run] press 0.500,0.500", "    [dry-run] release", "    [dry-run] cancel"]


def test_gpg_press_release_same_point_and_order(monkeypatch):
    inj, posts = _gpg(monkeypatch)
    t = inj.press(0.5, 0.5)
    assert isinstance(t, float)
    assert [m[0] for m in posts.msgs] == [WM_MOUSEMOVE, WM_LBUTTONDOWN]
    assert posts.msgs[1][1] == MK_LBUTTON
    assert posts.msgs[0][2:] == posts.msgs[1][2:]
    assert inj.release() is not None
    assert posts.msgs[2][0] == WM_LBUTTONUP
    assert posts.msgs[2][2:] == posts.msgs[1][2:]


def test_gpg_cancel_ends_with_up_below_press_point(monkeypatch):
    inj, posts = _gpg(monkeypatch)
    inj.press(0.5, 0.5)
    _, _, px, py = posts.msgs[1]
    posts.msgs.clear()
    inj.cancel()
    moves, up = posts.msgs[:-1], posts.msgs[-1]
    assert len(moves) == 6
    assert all(m[0] == WM_MOUSEMOVE and m[1] == MK_LBUTTON and m[2] == px for m in moves)
    assert [m[3] for m in moves] == sorted(m[3] for m in moves) and moves[0][3] > py
    assert up[0] == WM_LBUTTONUP and up[2] == px
    assert up[3] == py + 240          # 0.12 of the 2000 px content height
    assert moves[-1][3] == up[3]


def test_gpg_press_honours_clamp_box(monkeypatch):
    inj, posts = _gpg(monkeypatch)
    for _ in range(30):
        posts.msgs.clear()
        inj.press(0.5, 0.5, clamp=(0.4995, 0.4995, 0.5005, 0.5005))     # 1 px box either side
        _, _, x, y = posts.msgs[1]
        assert 599 <= x <= 601 and 1049 <= y <= 1051


def test_gpg_timing_interface(monkeypatch):
    inj, _ = _gpg(monkeypatch)
    assert (inj.press_lead, inj.start_delay(), inj.uses_swipe) == (0.25, 0.0, False)
    assert (PRESS_LEAD_GPG, PRESS_LEAD_LD) == (0.25, 0.6)
    with pytest.raises(NotImplementedError):
        inj.release_swipe(1.0, lambda: 0.0, lambda s: None)


# ---------------------------------------------------------------- LD (adb)

class FakeAdb:
    """Fakes subprocess.run (probe/_out) and subprocess.Popen (timed calls); records kwargs."""

    def __init__(self, getevent=GETEVENT_OK, writable=True):
        self.getevent, self.writable = getevent, writable
        self.runs, self.popens = [], []

    def run(self, cmd, **kw):
        self.runs.append((cmd, kw))
        args = cmd[4:]
        out = b""
        if args[:2] == ["getevent", "-pl"]:
            out = self.getevent.encode()
        elif args[0] == "test":
            out = b"W\n" if self.writable else b""
        kw["stdout"].write(out)

    def Popen(self, cmd, **kw):
        self.popens.append((cmd, kw))
        return SimpleNamespace(poll=lambda: 0)

    def all_calls(self):
        return self.runs + self.popens


def _ld(monkeypatch, **kw):
    fake = FakeAdb(**kw)
    monkeypatch.setattr(inject.subprocess, "run", fake.run)
    monkeypatch.setattr(inject.subprocess, "Popen", fake.Popen)
    inj = AdbInjector(execute=False, config=LD)
    inj.execute, inj.device = True, "dev1"
    return inj, fake


def _no_pipes(fake):
    for _, kw in fake.all_calls():
        assert kw.get("stdout") is not subprocess.PIPE and kw.get("stderr") is not subprocess.PIPE
        assert kw.get("stderr") is subprocess.DEVNULL
        assert "capture_output" not in kw


def test_adb_dry_run_runs_nothing_and_prints(monkeypatch, capsys):
    fake = FakeAdb()
    monkeypatch.setattr(inject.subprocess, "run", fake.run)
    monkeypatch.setattr(inject.subprocess, "Popen", fake.Popen)
    inj = AdbInjector(config=LD)
    inj.press(0.5, 0.5)
    inj.release()
    inj.cancel()
    assert fake.all_calls() == []
    assert capsys.readouterr().out.splitlines() == [
        "    [dry-run] press 0.500,0.500", "    [dry-run] release", "    [dry-run] cancel"]
    assert inj.uses_swipe is True and inj.start_delay() == 0.0 and fake.all_calls() == []


def test_probe_writable_multitouch_is_sendevent(monkeypatch):
    inj, fake = _ld(monkeypatch)
    assert inj.probe_release_method() == ("sendevent", "/dev/input/event2", (1439, 2559))
    cmds = [c[4:] for c, _ in fake.runs]
    assert cmds[0] == ["getevent", "-pl"]
    assert cmds[1][:2] == ["test", "-w"]
    assert cmds[2:] == [["true"]] * 5
    assert inj.probe_release_method() == ("sendevent", "/dev/input/event2", (1439, 2559))
    assert len(fake.runs) == 7            # cached: no second probe
    assert inj.uses_swipe is False and inj.start_delay() == 0.0
    _no_pipes(fake)


@pytest.mark.parametrize("kw", [dict(writable=False), dict(getevent=GETEVENT_NO_MT)])
def test_probe_falls_back_to_swipe(monkeypatch, kw):
    inj, fake = _ld(monkeypatch, **kw)
    assert inj.probe_release_method() == ("swipe", None, None)
    assert inj.uses_swipe is True
    _no_pipes(fake)


def test_swipe_start_delay_is_median_of_five_timings(monkeypatch):
    inj, fake = _ld(monkeypatch, writable=False)
    ticks = iter([0.0, 0.5, 1.0, 1.1, 2.0, 2.3, 3.0, 3.2, 4.0, 4.4])     # durations .5 .1 .3 .2 .4
    monkeypatch.setattr(inject.time, "perf_counter", lambda: next(ticks))
    inj.probe_release_method()
    assert inj.start_delay() == pytest.approx(statistics.median([0.5, 0.1, 0.3, 0.2, 0.4]))
    assert inj.press_lead == 0.6


def test_sendevent_command_strings_and_scaling(monkeypatch):
    inj, fake = _ld(monkeypatch)
    inj.press(0.5, 0.5)
    assert len(fake.popens) == 1
    cmd, kw = fake.popens[0]
    assert cmd[:4] == [inj.adb, "-s", "dev1", "shell"] and len(cmd) == 5      # one chained shell command
    d = "/dev/input/event2"
    x, y = inj._down[:2]
    assert abs(x - 0.5 * 1440) <= 5 and abs(y - 0.5 * 2560) <= 5              # scaled to the axis range
    assert cmd[4] == (f"sendevent {d} 3 57 1; sendevent {d} 3 53 {x}; sendevent {d} 3 54 {y}; "
                      f"sendevent {d} 1 330 1; sendevent {d} 0 0 0")
    inj.release()
    assert fake.popens[1][0][4] == (f"sendevent {d} 3 57 -1; sendevent {d} 1 330 0; sendevent {d} 0 0 0")
    _no_pipes(fake)


def test_sendevent_cancel_moves_below_then_releases(monkeypatch):
    inj, fake = _ld(monkeypatch)
    inj.press(0.5, 0.5)
    x = inj._down[0]
    inj.cancel()
    d = "/dev/input/event2"
    y2 = int((0.5 + 0.12) * 2560)
    assert fake.popens[1][0][4] == (
        f"sendevent {d} 3 53 {x}; sendevent {d} 3 54 {y2}; sendevent {d} 0 0 0; "
        f"sendevent {d} 3 57 -1; sendevent {d} 1 330 0; sendevent {d} 0 0 0")
    _no_pipes(fake)


def test_swipe_press_records_only_and_cancel_is_silent(monkeypatch):
    inj, fake = _ld(monkeypatch, writable=False)
    inj.press(0.5, 0.5)
    assert fake.popens == [] and inj.release() is None and inj.cancel() is None
    assert fake.popens == []


def test_release_swipe_spawns_at_t_release_minus_delay_and_lead(monkeypatch):
    inj, fake = _ld(monkeypatch, writable=False)
    inj.probe_release_method()
    inj._spawn_delay = 0.2
    inj.press(0.5, 0.5)
    x, y = inj._down
    now = [10.0]
    slept = []

    def sleeper(s):
        slept.append(s)
        now[0] += s

    spawned = inj.release_swipe(12.0, lambda: now[0], sleeper)
    assert slept == [pytest.approx(12.0 - 0.2 - 0.6 - 10.0)]
    assert spawned == pytest.approx(11.2)
    cmd, kw = fake.popens[0]
    assert cmd[4] == f"input swipe {x} {y} {x} {y} 600"
    _no_pipes(fake)


def test_release_swipe_sends_nothing_when_time_has_passed(monkeypatch):
    inj, fake = _ld(monkeypatch, writable=False)
    inj.probe_release_method()
    inj._spawn_delay = 0.2
    inj.press(0.5, 0.5)
    assert inj.release_swipe(12.0, lambda: 11.5, lambda s: pytest.fail("slept")) is None
    assert fake.popens == []


def test_method_line_texts():
    assert method_line(("sendevent", "/dev/input/event2", (1439, 2559))) == "LD 입력 방식: sendevent (/dev/input/event2)"
    assert method_line(("swipe", None, None)) == "LD 입력 방식: input swipe (정확도 낮음)"
