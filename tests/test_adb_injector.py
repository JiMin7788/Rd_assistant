import importlib.util
import subprocess
from pathlib import Path

import numpy as np
import pytest

from rdom.input import inject
from rdom.input.inject import AdbInjector, Injector, make_injector, parse_wm_size, resolve_device

ROOT = Path(__file__).resolve().parents[1]
LD = str(ROOT / "config" / "recorder_ld.toml")
GPG = str(ROOT / "config" / "recorder.toml")


class FakeRun:
    """Stands in for subprocess.run: records calls and writes `out` into a stdout file."""

    def __init__(self, out=b""):
        self.calls = []
        self.out = out

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        fh = kw.get("stdout")
        if fh is not None and fh not in (subprocess.PIPE, subprocess.DEVNULL):
            fh.write(self.out.decode() if "b" not in fh.mode else self.out)


def _live(monkeypatch):
    """An executing AdbInjector whose adb calls are faked."""
    fake = FakeRun()
    monkeypatch.setattr(inject.subprocess, "run", fake)
    inj = AdbInjector(execute=False, config=LD)
    inj.execute, inj.device = True, "dev1"
    return inj, fake


def test_dry_run_prints_and_calls_nothing(monkeypatch, capsys):
    fake = FakeRun()
    monkeypatch.setattr(inject.subprocess, "run", fake)
    inj = AdbInjector(config=LD)
    assert inj.execute is False
    inj.tap(0.5, 0.5)
    inj.swipe(0.1, 0.1, 0.2, 0.2)
    inj.back()
    inj.launch_game()
    assert inj.game_in_front() is None
    out = capsys.readouterr().out
    assert "[dry-run] input tap" in out and "input keyevent 4" in out
    assert "am start -n com.percent.aos.randomdice2/com.unity3d.player.UnityPlayerActivity" in out
    assert fake.calls == []


def test_execute_never_pipes(monkeypatch):
    inj, fake = _live(monkeypatch)
    inj.tap(0.5, 0.5)
    inj.swipe(0.1, 0.1, 0.9, 0.9, 200)
    inj.back()
    inj.launch_game()
    inj.game_in_front()
    assert len(fake.calls) == 5
    for cmd, kw in fake.calls:
        assert cmd[:3] == [inj.adb, "-s", "dev1"]
        assert kw.get("stdout") is not subprocess.PIPE and kw.get("stderr") is not subprocess.PIPE
        assert kw.get("stderr") is subprocess.DEVNULL
        assert "capture_output" not in kw
    assert fake.calls[2][0][-3:] == ["input", "keyevent", "4"]


def test_game_in_front(monkeypatch):
    inj, fake = _live(monkeypatch)
    for out, want in [(b"  mCurrentFocus=Window{1 u0 com.percent.aos.randomdice2/x}", True),
                      (b"  mCurrentFocus=Window{1 u0 com.android.launcher3/x}", False),
                      (b"nothing here", None)]:
        fake.out = out
        assert inj.game_in_front() is want


@pytest.mark.parametrize("exc", [OSError(22, "adb crashed"), FileNotFoundError("adb.exe"),
                                 subprocess.TimeoutExpired("adb", 10)])
def test_game_in_front_none_when_adb_cannot_run(monkeypatch, exc):
    inj, _ = _live(monkeypatch)

    def boom(cmd, **kw):
        raise exc
    monkeypatch.setattr(inject.subprocess, "run", boom)
    assert inj.game_in_front() is None


def test_resolve_device(monkeypatch):
    def attached(listing):
        monkeypatch.setattr(inject.subprocess, "run", FakeRun(listing.encode()))
    hdr = "List of devices attached\n"
    attached(hdr + "emulator-5554\tdevice\n127.0.0.1:5555\tdevice\n")
    assert resolve_device("adb", "127.0.0.1:5555") == "127.0.0.1:5555"
    attached(hdr + "emulator-5554\tdevice\n")
    assert resolve_device("adb", "127.0.0.1:5555") == "emulator-5554"
    attached(hdr + "emulator-5554\tdevice\nemulator-5556\tdevice\n")
    with pytest.raises(RuntimeError):
        resolve_device("adb", "127.0.0.1:5555")
    attached(hdr + "emulator-5554\toffline\n")
    with pytest.raises(RuntimeError):
        resolve_device("adb", "x")


def test_parse_wm_size():
    assert parse_wm_size("Physical size: 1440x2560\n") == (1440, 2560)
    assert parse_wm_size("Physical size: 1440x2560\nOverride size: 1080x1920\n") == (1080, 1920)
    assert parse_wm_size("") is None
    assert parse_wm_size("error: closed") is None


def _exec_init(monkeypatch, wm_out, capsys):
    monkeypatch.setattr(inject, "resolve_device", lambda adb, preferred="": "dev1")
    monkeypatch.setattr(inject.subprocess, "run", FakeRun(wm_out))
    inj = AdbInjector(execute=True, config=LD)
    return inj, capsys.readouterr().out


def test_wm_size_read_on_execute(monkeypatch, capsys):
    inj, out = _exec_init(monkeypatch, b"Physical size: 1440x2560\n", capsys)
    assert (inj.res_w, inj.res_h) == (1440, 2560) and "wm size unreadable" not in out
    inj, _ = _exec_init(monkeypatch, b"Physical size: 1440x2560\nOverride size: 720x1280\n", capsys)
    assert (inj.res_w, inj.res_h) == (720, 1280)
    inj, out = _exec_init(monkeypatch, b"", capsys)
    assert (inj.res_w, inj.res_h) == (1440, 2560)
    assert "adb: wm size unreadable -- using 1440x2560" in out


def test_px_clamps():
    for _ in range(50):
        x, y = inject._px(0.0, 0.0, 1440, 2560)
        assert 0 <= x <= 5 and 0 <= y <= 5
        x, y = inject._px(1.0, 1.0, 1440, 2560)
        assert 1434 <= x <= 1439 and 2554 <= y <= 2559
        x, y = inject._px(1.5, -0.5, 1440, 2560)         # outside the screen: clamped
        assert (x, y) == (1439, 0)
    assert inject._px(0.5, 0.5, 1000, 2000, jitter=0) == (500, 1000)


def test_shared_action_logic():
    assert AdbInjector.execute_action is Injector.execute_action
    assert AdbInjector.cheong_ready is Injector.cheong_ready


def test_execute_action_on_adb(capsys):
    inj = AdbInjector(config=LD)
    assert inj.execute_action({"op": "summon"}) is True
    assert inj.execute_action({"op": "destroy", "cell": 3}) is True
    assert inj.execute_action({"op": "destroy", "cell": 3}) is False   # cheong cooldown
    assert inj.cheong_cooldown_left() > 80
    assert "[dry-run] input swipe" in capsys.readouterr().out


def test_make_injector_picks_class():
    assert type(make_injector(LD, execute=False)) is AdbInjector
    assert type(make_injector(GPG, execute=False)) is Injector


def _load_save_frame():
    spec = importlib.util.spec_from_file_location("save_frame_tool2", ROOT / "tools" / "save_frame.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGrabber:
    def __init__(self, covered=False):
        self.covered, self.closed = covered, False

    def grab(self):
        return np.zeros((8, 8, 3), np.uint8)

    def unobscured(self):
        return not self.covered

    def close(self):
        self.closed = True


def test_save_frame_every_writes_without_overwriting(tmp_path):
    mod = _load_save_frame()
    t = [0.0]
    n = mod.run_every(FakeGrabber(), tmp_path / "ld_x", 5, 0.5,
                      sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    files = sorted((tmp_path / "ld_x").glob("*.png"))
    assert n == 7 and len(files) == 7           # t = 0, 5, ... 30 s
    assert len({f.name for f in files}) == 7     # same-second stamps get _N suffixes


def test_save_frame_every_covered_saves_nothing(tmp_path):
    mod = _load_save_frame()
    t = [0.0]
    n = mod.run_every(FakeGrabber(covered=True), tmp_path / "c", 5, 0.2,
                      sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    assert n == 0 and not list((tmp_path / "c").glob("*.png"))


def test_save_frame_main_profile_and_exit(tmp_path, monkeypatch):
    mod = _load_save_frame()
    monkeypatch.setattr(mod, "MANUAL", tmp_path)
    seen = []

    def factory(config):
        seen.append(config)
        return FakeGrabber(covered=True)

    assert mod.main(["--profile", "ld", "--every", "1", "--minutes", "0.01"], grabber_factory=factory) == 1
    assert seen == ["config/recorder_ld.toml"]
    assert mod.main([], grabber_factory=lambda config: FakeGrabber()) == 0
    assert len(list(tmp_path.glob("*.png"))) == 1
    with pytest.raises(SystemExit):
        mod.main(["--every", "5"], grabber_factory=factory)


def test_gear_bot_has_profile_option():
    text = (ROOT / "tools" / "gear_bot.py").read_text(encoding="utf-8")
    assert '"--profile"' in text and "make_injector(" in text and "LiveGrabber(config=" in text
