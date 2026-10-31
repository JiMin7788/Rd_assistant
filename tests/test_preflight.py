"""rdF04 t7: start check (capture/preflight.py) and tools/duo_check.py on fakes."""
import importlib.util
import subprocess
from pathlib import Path

from rdom.capture import preflight
from rdom.capture.preflight import check, format_lines
from rdom.recorder.config import load_config
from rdom.recorder.geometry import Rect

ROOT = Path(__file__).resolve().parents[1]
LD_RE = load_config(ROOT / "config" / "recorder_ld.toml").target.window_title_re
GPG_RE = load_config(ROOT / "config" / "recorder.toml").target.window_title_re

LD_RECT = Rect(16, 80, 1138, 2074)
GPG_RECT = Rect(3100, 80, 4200, 2000)


class FakeGrabber:
    def __init__(self, cfg, rects, covered):
        self.is_ld = "recorder_ld" in str(cfg)
        self.rect = rects["ld" if self.is_ld else "gpg"]
        self.covered = covered
        self.closed = False

    def unobscured(self):
        return not self.covered

    def content_rect(self):
        return self.rect, None

    def grab(self):
        return object()

    def close(self):
        self.closed = True


class Env:
    """Fakes for every seam; `windows` maps title_re -> number of matching windows."""

    def __init__(self, windows=None, covered=(), adb_ok=True, ld=LD_RECT, gpg=GPG_RECT):
        self.windows = {LD_RE: 1, GPG_RE: 1} if windows is None else windows
        self.covered, self.adb_ok = set(covered), adb_ok
        self.rects = {"ld": ld, "gpg": gpg}
        self.placed, self.adb_calls = [], []

    def finder(self, title_re):
        n = self.windows.get(title_re, 0)
        if n == 0:
            raise RuntimeError(f"no visible window matching {title_re!r}")
        if n > 1:
            raise RuntimeError(f"{n} windows match {title_re!r}: a, b")
        return 1

    def placer(self, cfg):
        self.placed.append(Path(cfg).name)

    def grabber(self, cfg):
        name = "ld" if "recorder_ld" in str(cfg) else "gpg"
        return FakeGrabber(cfg, self.rects, name in self.covered)

    def adb(self, adb, serial):
        self.adb_calls.append((adb, serial))
        return self.adb_ok

    def run(self, names, **kw):
        return check(names, finder=self.finder, placer=self.placer,
                     grabber_factory=self.grabber, adb_probe=self.adb, **kw)


def lines(env, names):
    return format_lines(env.run(names))


def test_window_missing_texts():
    assert lines(Env(windows={GPG_RE: 1}), ["ld"]) == ["start check: FAIL LD플레이어 창이 없어요"]
    assert lines(Env(windows={LD_RE: 1}), ["gpg"]) == [
        "start check: FAIL 구글플레이게임즈 랜덤 다이스 창이 없어요"]


def test_two_windows():
    env = Env(windows={LD_RE: 2, GPG_RE: 1})
    assert lines(env, ["ld"]) == [f"start check: FAIL {LD_RE} 창이 2개 이상이에요"]
    assert env.placed == [] and env.adb_calls == []


def test_covered():
    env = Env(covered={"gpg"})
    assert lines(env, ["gpg"]) == ["start check: FAIL 다른 창이 게임 화면을 가리고 있어요"]


def test_adb_missing_ld_only():
    env = Env(adb_ok=False)
    assert lines(env, ["ld"]) == [
        "start check: FAIL LD플레이어 adb 연결이 안 돼요 (LD 설정 → 기타 설정 → ADB 디버깅: 로컬 연결)"]
    assert env.adb_calls == [("D:\\LDPlayer\\LDPlayer14\\adb.exe", "127.0.0.1:5555")]


def test_adb_probe_not_called_for_gpg():
    env = Env(adb_ok=False)
    assert lines(env, ["gpg"]) == ["start check: OK 구글플레이게임즈 랜덤 다이스 준비됐어요"]
    assert env.adb_calls == []


def test_overlap_of_two_profiles():
    env = Env(gpg=Rect(1000, 80, 2100, 2000))
    assert lines(env, ["ld", "gpg"]) == [
        "start check: OK LD플레이어 준비됐어요",
        "start check: OK 구글플레이게임즈 랜덤 다이스 준비됐어요",
        "start check: FAIL 두 게임 창이 겹쳐요"]


def test_all_ok_places_and_closes():
    env = Env()
    grabbed = []
    res = check(["ld", "gpg"], finder=env.finder, placer=env.placer,
                grabber_factory=lambda c: grabbed.append(env.grabber(c)) or grabbed[-1],
                adb_probe=env.adb, grab=True)
    assert format_lines(res) == [
        "start check: OK LD플레이어 준비됐어요",
        "start check: OK 구글플레이게임즈 랜덤 다이스 준비됐어요",
        "start check: OK 두 게임 창이 겹치지 않아요"]
    assert env.placed == ["recorder_ld.toml", "recorder.toml"]
    assert all(g.closed for g in grabbed)
    assert Env().run(["ld"], place=False) and Env().placed == []


def test_no_place_when_disabled():
    env = Env()
    env.run(["ld", "gpg"], place=False)
    assert env.placed == []


def put(fh, text):
    """Write into the temp file adb output goes to (text or binary mode)."""
    fh.write(text if "b" not in getattr(fh, "mode", "") else text.encode())


def test_real_adb_probe_is_read_only_and_pipe_free(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        assert "stdout" in kw and kw["stdout"] != subprocess.PIPE
        assert not kw.get("capture_output") and kw.get("stderr") != subprocess.PIPE
        put(kw["stdout"], "List of devices attached\n127.0.0.1:5555\tdevice\n"
            if cmd[1] == "devices" else "Physical size: 1440x2560\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert preflight.adb_probe("adb.exe", "127.0.0.1:5555") is True
    assert calls == [["adb.exe", "devices"],
                     ["adb.exe", "-s", "127.0.0.1:5555", "shell", "wm", "size"]]


def test_real_adb_probe_false_without_device(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: put(
        kw["stdout"], "List of devices attached\n"))
    assert preflight.adb_probe("adb.exe", "") is False


# ---- tools/duo_check.py -----------------------------------------------------------------

def load_duo():
    spec = importlib.util.spec_from_file_location("duo_check", ROOT / "tools" / "duo_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeProc:
    def __init__(self, log, name, code, out):
        self.log, self.name, self.returncode, self.out = log, name, code, out

    def communicate(self):
        self.log.append(("wait", self.name))
        return self.out, ""


def run_duo(capsys, check_results, codes):
    duo, log = load_duo(), []

    def spawn(name):
        log.append(("start", name))
        return FakeProc(log, name, codes[name], "(1994, 1122, 3)\n" if codes[name] == 0 else "")

    rc = duo.main([], check_fn=lambda names, place: check_results, spawn=spawn)
    return rc, capsys.readouterr().out.splitlines(), log


OK = [("ld", True, "LD플레이어 준비됐어요"), ("gpg", True, "구글플레이게임즈 랜덤 다이스 준비됐어요")]


def test_duo_check_ok_starts_both_before_waiting(capsys):
    rc, out, log = run_duo(capsys, OK, {"ld": 0, "gpg": 0})
    assert rc == 0
    assert log == [("start", "ld"), ("start", "gpg"), ("wait", "ld"), ("wait", "gpg")]
    assert out == ["start check: OK LD플레이어 준비됐어요",
                   "start check: OK 구글플레이게임즈 랜덤 다이스 준비됐어요",
                   "start check: OK ld 프레임 (1994, 1122, 3)",
                   "start check: OK gpg 프레임 (1994, 1122, 3)"]


def test_duo_check_child_failure_exits_1(capsys):
    rc, out, _ = run_duo(capsys, OK, {"ld": 0, "gpg": 1})
    assert rc == 1 and out[-1] == "start check: FAIL gpg 프레임을 못 읽었어요"


def test_duo_check_preflight_failure_spawns_nothing(capsys):
    bad = [("ld", False, "LD플레이어 창이 없어요")]
    rc, out, log = run_duo(capsys, bad, {"ld": 0, "gpg": 0})
    assert rc == 1 and log == [] and out == ["start check: FAIL LD플레이어 창이 없어요"]


def test_duo_check_source_has_no_injector_or_writer():
    src = (ROOT / "tools" / "duo_check.py").read_text(encoding="utf-8")
    for bad in ("inject", "save_frame", "imwrite", "collect"):
        assert bad not in src.replace("never injects input and never saves", "")
