"""tests/test_minigame_bot.py -- tools/minigame_bot.py on fakes: virtual clock, synthetic gauge frames, fake injector.

The synthetic game draws real gauge frames (622x1116) that the real detector reads, sweeps the tip as a
triangle wave on a 60 fps frame grid and stops it at the first frame at or after the UP's arrival.
Nothing here touches a window, a capture device, adb or C:/dev/rdom/data (tmp dirs only).
"""
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
REC = Path("C:/dev/_hub/features/minigame/rec/gpg_20261102_003916.mp4")
TRACES = ROOT / "tests" / "fixtures" / "rdf05" / "traces.json"


def _load(name="minigame_bot_under_test"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "minigame_bot.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bot = _load()

W, H = 622, 1116
COL = {"blue": (77, 154, 253), "purple": (171, 77, 251), "yellow": (250, 210, 48), "dark": (32, 24, 49),
       "tri": (253, 0, 97), "green": (35, 239, 190)}
BAR_Y, TRI_Y, BTN_Y = (610, 630), (634, 658), (760, 840)
BTN_U = (0.30, 0.70)
AIM = bot.AIM_FRAC / 60.0           # the loop aims this much earlier than the latency estimate (60 fps game)


# ---------------------------------------------------------------- the synthetic game
def _px(u):
    return int(round(u * W))


_BASE = {}


def _base(yc):
    if yc not in _BASE:
        img = np.zeros((H, W, 3), np.uint8)
        y0, y1 = BAR_Y
        img[y0:y1, _px(0.14):_px(0.86)] = COL["dark"]
        yl, yr = yc - 0.015, yc + 0.015
        edges = [0.16, yl - 0.10, yl, yr, yr + 0.10, 0.84]
        for name, a, b in zip(("blue", "purple", "yellow", "purple", "blue"), edges[:-1], edges[1:]):
            img[y0:y1, _px(a):_px(b)] = COL[name]
        img[BTN_Y[0]:BTN_Y[1], _px(BTN_U[0]):_px(BTN_U[1])] = COL["green"]
        _BASE[yc] = img
    return _BASE[yc]


def _tri(x):
    f = x - math.floor(x)
    return 1.0 - abs(2.0 * f - 1.0)


class VClock:
    """Virtual clock: every call to the clock moves it 20 us, so a spin loop terminates."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        self.now += 2e-5
        return self.now

    def sleep(self, dt):
        if dt > 0:
            self.now += dt


class Game:
    def __init__(self, clock, *, t_start, yc=0.5, speed=2.0, lo=0.16, hi=0.84, fps=60.0, fphase=0.0031,
                 latency=0.058):
        self.clock, self.t_start, self.yc = clock, t_start, yc
        self.lo, self.hi, self.fp, self.fphase = lo, hi, 1.0 / fps, fphase
        self.period = 2.0 / speed
        self.latency = latency              # UP send -> arrival at the game
        self.stop_k = None

    def k_at(self, now):
        return math.floor((now - self.fphase) / self.fp)

    def frame_time(self, k):
        return self.fphase + k * self.fp

    def content_id(self, now):
        k = self.k_at(now)
        return k if self.stop_k is None else min(k, self.stop_k)

    def next_visible(self, now):
        k = self.k_at(now)
        if self.stop_k is not None and k >= self.stop_k:
            return None
        return self.frame_time(k + 1)

    def register_stop(self, arrival):
        """The tip freezes at the first game frame at or after `arrival`."""
        if self.stop_k is None:
            self.stop_k = math.ceil((arrival - self.fphase) / self.fp - 1e-9)

    def tip(self, k):
        return self.lo + (self.hi - self.lo) * _tri((self.frame_time(k) - self.t_start) / self.period)

    def yellow(self):
        return (self.yc - 0.015, self.yc + 0.015)

    def render(self, cid):
        if self.frame_time(cid) < self.t_start:
            return np.zeros((H, W, 3), np.uint8)
        yc = self.yc(cid) if callable(self.yc) else self.yc
        img = _base(yc).copy()
        x = _px(self.tip(cid))
        img[TRI_Y[0]:TRI_Y[1], x - 12:x + 12] = COL["tri"]
        return img


class FakeSource:
    def __init__(self, game, clock, *, t_end, covered=False, moved=None, stall=None, unobscured_delays=()):
        self.game, self.clock, self.t_end = game, clock, t_end
        self.covered, self.moved, self.stall = covered, moved, stall
        self.unobscured_delays = list(unobscured_delays)
        self.unobscured_calls = 0
        self.last_cid = None
        self.closed = False

    def _end(self):
        if self.clock.now > self.t_end:
            raise bot.EndOfSource()

    def grab(self):
        self._end()
        self.clock.now += 0.004
        return self.game.render(self.game.content_id(self.clock.now))

    def grab_fresh(self, region_uv=None):
        self._end()
        if self.stall:
            self.clock.now += self.stall(self) or 0.0
        deadline = self.clock.now + 0.040
        while True:
            cid = self.game.content_id(self.clock.now)
            if cid != self.last_cid:
                break
            nxt = self.game.next_visible(self.clock.now)
            if nxt is None or nxt > deadline:
                self.clock.now = deadline
                return None, self.clock.now
            self.clock.now = nxt
        self.last_cid = cid
        t = self.clock.now
        self.clock.now += 0.0005
        return bot._crop(self.game.render(cid), region_uv), t

    def unobscured(self):
        self.unobscured_calls += 1
        if self.unobscured_delays:
            self.clock.now += self.unobscured_delays.pop(0)
        return not self.covered

    def window_moved(self):
        return bool(self.moved and self.moved(self))

    def close(self):
        self.closed = True


class FakeInjector:
    def __init__(self, game, clock, *, press_lead=0.25, start=0.0, swipe=False, registers=True,
                 cancel_stops=False, release_raises=False):
        self.game, self.clock = game, clock
        self.press_lead, self._start, self.uses_swipe = press_lead, start, swipe
        self.registers, self.cancel_stops, self.release_raises = registers, cancel_stops, release_raises
        self.calls = []

    def start_delay(self):
        return self._start

    def press(self, u, v, clamp=None):
        self.calls.append(("press", self.clock.now, u, v, clamp))
        return self.clock.now

    def release(self):
        if self.release_raises:
            raise KeyboardInterrupt()
        self.calls.append(("release", self.clock.now))
        if self.registers:
            self.game.register_stop(self.clock.now + self.game.latency)
        return self.clock.now

    def cancel(self):
        self.calls.append(("cancel", self.clock.now))
        if self.cancel_stops:
            self.game.register_stop(self.clock.now + self.game.latency)
        return self.clock.now

    def release_swipe(self, t_release, clock, sleeper):
        spawn_at = t_release - self._start - self.press_lead
        now = clock()
        if now > spawn_at:
            return None
        sleeper(spawn_at - now)
        t = self.clock.now
        self.calls.append(("spawn", t))
        if self.registers:
            self.game.register_stop(t + self._start + self.press_lead + self.game.latency)
        return t

    def kinds(self):
        return [c[0] for c in self.calls]


def run(tmp_path, monkeypatch, *, profile="gpg", execute=True, sim_s=4.5, inj_kw=None, game_kw=None,
        src_kw=None, cal=None, cancel_test=False, strips=True, manual_stop_s=None, fast_fit=True):
    """Build the fakes, run GaugeLoop to the end of the simulated source, return everything."""
    if fast_fit:
        monkeypatch.setattr(bot, "REFIT_S", 0.2)     # a fit takes 60-120 ms real time; keeps the suite quick
    clock = VClock()
    game = Game(clock, t_start=clock.now + 0.2, **(game_kw or {}))
    if manual_stop_s is not None:
        game.register_stop(game.t_start + manual_stop_s)
    src = FakeSource(game, clock, t_end=game.t_start + sim_s, **(src_kw or {}))
    inj = FakeInjector(game, clock, **(inj_kw or {}))
    plans = []
    src.plans, src.inj = plans, inj                 # lets a stall hook look at the plans and the input calls
    real_plan = bot.plan_release

    def spy(fit, fc, yellow, now, latency, **kw):
        p = real_plan(fit, fc, yellow, now, latency, **kw)
        plans.append(SimpleNamespace(now=now, kw=kw, plan=p, latency=latency))
        return p

    monkeypatch.setattr(bot, "plan_release", spy)
    out = []
    cal = cal or bot.LatencyCal(default=bot.DEFAULT_LATENCY[profile])
    lat_file = tmp_path / f"latency_{profile}.json"
    loop = bot.GaugeLoop(src, inj, clock=clock, sleeper=clock.sleep, profile=profile, execute=execute,
                         latency_cal=cal, records=tmp_path / "gauges.jsonl",
                         strips=(tmp_path / "strips") if strips else None, out=out.append,
                         latency_file=lat_file if execute else None, method="postmessage",
                         cancel_test=cancel_test, stamp=lambda: "S")
    code = loop.run()
    recs = []
    if (tmp_path / "gauges.jsonl").exists():
        recs = [json.loads(line) for line in (tmp_path / "gauges.jsonl").read_text(encoding="utf-8").splitlines()]
    return SimpleNamespace(loop=loop, code=code, out=out, inj=inj, src=src, game=game, plans=plans, recs=recs,
                           lat_file=lat_file, cal=cal, clock=clock)


# ---------------------------------------------------------------- import / command line
def test_import_has_no_side_effects(tmp_path, monkeypatch):
    from rdom.capture import live, preflight
    from rdom.input import inject

    def boom(*a, **k):
        raise AssertionError("touched the outside world on import")

    for obj, name in ((live.LiveGrabber, "__init__"), (inject.Injector, "__init__"),
                      (inject.AdbInjector, "__init__")):
        monkeypatch.setattr(obj, name, boom)
    monkeypatch.setattr(preflight, "check", boom)
    monkeypatch.chdir(tmp_path)
    mod = _load("minigame_bot_import_probe")
    assert callable(mod.main) and callable(mod.GaugeLoop)
    assert list(tmp_path.iterdir()) == []


def test_argparse_errors_exit_2(capsys):
    assert bot.main([]) == 2                                                  # --profile is required
    assert bot.main(["--profile", "gpg", "--replay", "x.mp4", "--execute"]) == 2
    assert bot.main(["--profile", "gpg", "--cancel-test"]) == 2               # --cancel-test needs --execute
    assert bot.main(["--profile", "ld", "--probe-input", "--execute"]) == 2
    assert bot.main(["--profile", "ld", "--probe-input", "--replay", "x.mp4"]) == 2
    assert "required" in capsys.readouterr().err


def test_probe_input(monkeypatch):
    out = []
    assert bot.main(["--profile", "gpg", "--probe-input"], out=out.append) == 0
    assert out == ["GPG는 창 메시지 입력이라 점검할 게 없어요"]

    class Adb:
        adb, device = "adb", "x"

        def probe_release_method(self):
            return ("sendevent", "/dev/input/event2", (1, 1))

    out = []
    seams = {"injector": lambda cfg, execute: Adb(), "resolve_device": lambda adb, dev: "127.0.0.1:5555"}
    assert bot.main(["--profile", "ld", "--probe-input"], seams=seams, out=out.append) == 0
    assert out == ["LD 입력 방식: sendevent (/dev/input/event2)"]


def test_replay_missing_file_exits_2_without_traceback(tmp_path):
    out = []
    assert bot.main(["--profile", "gpg", "--replay", str(tmp_path / "nope.mp4")], out=out.append) == 2
    assert out == [f"리플레이 파일을 열 수 없어요: {tmp_path / 'nope.mp4'}"]


# ---------------------------------------------------------------- start (AC2)
def _live_seams(tmp_path, monkeypatch, *, ok=True, injector=None, sim_s=-1.0):
    clock = VClock()
    game = Game(clock, t_start=clock.now + 0.2)
    src = FakeSource(game, clock, t_end=clock.now + sim_s)       # the source is "at its end" at once
    made = []

    def make_inj(cfg, execute):
        made.append(execute)
        return injector or FakeInjector(game, clock)

    seams = {"preflight": lambda profs, place: [("gpg", ok, "다른 창이 게임 화면을 가리고 있어요" if not ok else "ok")],
             "grabber": lambda cfg: src, "injector": make_inj, "clock": clock, "sleeper": clock.sleep,
             "data_dir": tmp_path}
    return seams, made, src


def test_failed_start_check_returns_3_and_creates_no_injector(tmp_path, monkeypatch):
    seams, made, _ = _live_seams(tmp_path, monkeypatch, ok=False)
    seams["grabber"] = lambda cfg: pytest.fail("grabber created after a failed start check")
    out = []
    assert bot.main(["--profile", "gpg", "--execute"], seams=seams, out=out.append) == 3
    assert out == ["⛔ 시작 점검 실패: 다른 창이 게임 화면을 가리고 있어요"]
    assert made == []


def test_start_lines_in_order(tmp_path, monkeypatch):
    (tmp_path / "latency_gpg.json").write_text(
        json.dumps({"samples": [0.05, 0.04], "updated": "x", "method": "postmessage"}), encoding="utf-8")
    seams, made, src = _live_seams(tmp_path, monkeypatch)
    out = []
    assert bot.main(["--profile", "gpg", "--execute"], seams=seams, out=out.append) == 0
    assert out[:4] == ["미니게임 봇 시작: 구글플레이게임즈 랜덤 다이스 · 실제 입력",
                       "대청소 시작은 직접 눌러 주세요. 끝내려면 Ctrl+C",
                       "지연 보정: 45 ms (저장값 2개)", "게이지 기다리는 중"]
    assert out[-1] == "미니게임 봇 종료: 게이지 0개 중 노랑 0개"
    assert made == [True] and src.closed
    seams, made, _ = _live_seams(tmp_path / "other", monkeypatch)
    out = []
    bot.main(["--profile", "gpg"], seams=seams, out=out.append)
    assert out[0].endswith("드라이런 (입력 안 함)") and out[2] == "지연 보정: 60 ms (기본값)" and made == [False]


def test_ld_execute_adds_method_line(tmp_path, monkeypatch):
    class Ld(FakeInjector):
        def probe_release_method(self):
            return ("swipe", None, None)

    clock = VClock()
    game = Game(clock, t_start=clock.now + 0.2)
    inj = Ld(game, clock, press_lead=0.6)
    seams, _, _ = _live_seams(tmp_path, monkeypatch, injector=inj)
    seams["preflight"] = lambda profs, place: [("ld", True, "ok")]
    out = []
    bot.main(["--profile", "ld", "--execute"], seams=seams, out=out.append)
    assert out[:5] == ["미니게임 봇 시작: LD플레이어 · 실제 입력", "대청소 시작은 직접 눌러 주세요. 끝내려면 Ctrl+C",
                       "지연 보정: 200 ms (기본값)", "LD 입력 방식: input swipe (정확도 낮음)", "게이지 기다리는 중"]


# ---------------------------------------------------------------- execute: timing (AC3, AC7)
def test_execute_gpg_press_and_release_times(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch)
    assert r.code == 0
    assert r.inj.kinds() == ["press", "release"]
    rec = r.recs[0]
    release_t = rec["planned_frame_t"] - rec["latency_used"]
    press, release = r.inj.calls
    assert press[1] == pytest.approx(release_t - 0.25, abs=0.002)
    assert release[1] == pytest.approx(release_t, abs=0.002)
    assert rec["release_sent_t"] == pytest.approx(release_t, abs=0.002)
    bx = (_px(BTN_U[0]) / W, BTN_Y[0] / H, _px(BTN_U[1]) / W, BTN_Y[1] / H)
    assert press[2] == pytest.approx((bx[0] + bx[2]) / 2, abs=0.002)
    assert press[3] == pytest.approx((bx[1] + bx[3]) / 2, abs=0.002)
    assert press[4] == pytest.approx(bx, abs=0.002)                  # the clamp is the button box
    assert all(p.kw["lead_min"] == pytest.approx(0.25 + 0.0 + 0.060 + AIM + 0.10, abs=1e-4) for p in r.plans)
    assert r.out.count("게이지 1: 놓음 (지연 60 ms)") == 1
    assert "게이지 1 결과: 노랑 (완벽해) · 누적 노랑 1/1" in r.out
    assert r.out[-1] == "미니게임 봇 종료: 게이지 1개 중 노랑 1개"
    assert press[1] >= max(p.now for p in r.plans if p.now < press[1])     # never before the plan time


def test_execute_ld_sendevent_uses_ld_lead(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, profile="ld", sim_s=5.5, inj_kw={"press_lead": 0.6},
            game_kw={"latency": 0.198}, cal=bot.LatencyCal(default=0.2))
    assert r.inj.kinds() == ["press", "release"]
    assert all(p.kw["lead_min"] == pytest.approx(0.9 + AIM, abs=1e-4) for p in r.plans)
    rec = r.recs[0]
    release_t = rec["planned_frame_t"] - rec["latency_used"]
    assert r.inj.calls[0][1] == pytest.approx(release_t - 0.6, abs=0.002)
    assert r.inj.calls[0][1] >= max(p.now for p in r.plans if p.plan is not None and p.now < r.inj.calls[0][1])
    assert r.inj.calls[1][1] == pytest.approx(release_t, abs=0.002)
    assert rec["zone"] == "노랑 (완벽해)"


def test_execute_ld_swipe_calls_release_swipe(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, profile="ld", sim_s=5.5,
            inj_kw={"press_lead": 0.6, "start": 0.08, "swipe": True}, game_kw={"latency": 0.198},
            cal=bot.LatencyCal(default=0.2))
    assert r.inj.kinds() == ["press", "spawn"]              # press keeps the point, the swipe is the release
    assert all(p.kw["lead_min"] == pytest.approx(0.6 + 0.08 + 0.2 + AIM + 0.1, abs=1e-4) for p in r.plans)
    spawn = r.inj.calls[1][1]
    assert spawn >= max(p.now for p in r.plans if p.plan is not None and p.now < spawn)
    rec = r.recs[0]
    assert spawn == pytest.approx(rec["planned_frame_t"] - rec["latency_used"] - 0.08 - 0.6, abs=0.002)
    assert rec["zone"] == "노랑 (완벽해)"


def test_stalled_check_after_plan_sends_nothing_and_replans(tmp_path, monkeypatch):
    # the visible-window check takes 0.5 s the first time: the planned DOWN time is past when it returns
    r = run(tmp_path, monkeypatch, sim_s=7.0, src_kw={"unobscured_delays": [0.5]})
    assert r.src.unobscured_calls >= 2
    assert r.inj.kinds() == ["press", "release"]            # only the second, in-time attempt was sent
    press_t = r.inj.calls[0][1]
    assert press_t >= max(p.now for p in r.plans if p.plan is not None and p.now < press_t)
    rec = r.recs[0]
    assert press_t == pytest.approx(rec["planned_frame_t"] - rec["latency_used"] - 0.25, abs=0.002)
    assert rec["zone"] == "노랑 (완벽해)"


def test_stalled_grab_past_first_action_replans(tmp_path, monkeypatch):
    state = {"stalled": False}

    def stall(src):
        last = next((p for p in reversed(src.plans) if p.plan is not None), None)
        if last is None or state["stalled"] or src.inj.calls:
            return 0.0
        state["stalled"] = True
        return last.plan.release_t - 0.25 - src.clock.now + 0.05    # this grab returns after the first action time

    r = run(tmp_path, monkeypatch, sim_s=8.0, src_kw={"stall": stall})
    assert state["stalled"], "the scenario never stalled a grab after a plan"
    assert r.inj.kinds() == ["press", "release"]
    press_t = r.inj.calls[0][1]
    rec = r.recs[0]
    # the press that was sent belongs to a plan made after the stall, never to the stale one
    assert press_t == pytest.approx(rec["planned_frame_t"] - rec["latency_used"] - 0.25, abs=0.002)
    assert press_t >= max(p.now for p in r.plans if p.plan is not None and p.now < press_t)
    assert rec["zone"] == "노랑 (완벽해)"


# ---------------------------------------------------------------- dry run
def test_dry_run_never_presses_and_prints_would_line(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, execute=False, sim_s=5.0, manual_stop_s=3.6)
    assert r.inj.calls == []
    assert r.out.count("게이지 1: [드라이런] 여기서 놓았을 거예요") == 1
    assert any(line.startswith("게이지 1 결과 (직접 멈춤): ") for line in r.out)
    assert not r.lat_file.exists()                          # a dry run never writes the latency file
    assert r.recs[0]["execute"] is False and r.recs[0]["manual"] is True
    assert r.out[-1] == "미니게임 봇 종료: 게이지 0개 중 노랑 0개"


# ---------------------------------------------------------------- guards (AC4)
def test_confirm_needs_two_equal_reads(tmp_path, monkeypatch):
    # the yellow interval changes on every frame: no two consecutive reads agree
    r = run(tmp_path, monkeypatch, sim_s=2.0, game_kw={"yc": lambda k: 0.45 + 0.05 * (k % 2)})
    assert r.inj.calls == [] and r.loop.n == 0 and r.recs == []
    assert r.out == ["미니게임 봇 종료: 게이지 0개 중 노랑 0개"]


def test_covered_game_gets_no_press_and_one_warning(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, sim_s=6.0, src_kw={"covered": True})
    assert r.inj.calls == []
    assert r.out.count("⚠ 다른 창이 게임을 가려서 이번엔 안 눌러요") == 1
    assert r.src.unobscured_calls >= 2                      # it tried again, still quiet


def test_three_unregistered_releases_stop_with_exit_3(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, sim_s=25.0, inj_kw={"registers": False})
    assert r.code == 3
    assert [line for line in r.out if line.startswith("⚠ 게이지 1: 놓았는데")] == [
        "⚠ 게이지 1: 놓았는데 삼각형이 안 멈췄어요 (1/3)", "⚠ 게이지 1: 놓았는데 삼각형이 안 멈췄어요 (2/3)",
        "⚠ 게이지 1: 놓았는데 삼각형이 안 멈췄어요 (3/3)"]
    assert r.out[-1] == "⛔ 멈춰 입력이 3번 연속 먹히지 않아서 멈춰요"
    assert r.inj.kinds().count("release") == 3 and r.inj.kinds()[-1] == "cancel"
    assert r.loop.m == 0


def test_window_moved_cancels_and_exits_3(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, src_kw={"moved": lambda s: True})
    assert r.code == 3 and r.out == ["⛔ 게임 창이 움직여서 멈춰요"]
    assert r.inj.kinds() == ["cancel"]


def test_window_moved_right_after_hold(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, src_kw={"moved": lambda s: "release" in s.inj.kinds()})
    assert r.code == 3 and r.out[-1] == "⛔ 게임 창이 움직여서 멈춰요"
    assert r.inj.kinds() == ["press", "release", "cancel"]  # checked right after the hold, held press cancelled


def test_ctrl_c_during_hold_cancels_not_releases(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, inj_kw={"release_raises": True})
    assert r.code == 0
    assert r.inj.kinds() == ["press", "cancel"]
    assert r.out[-1] == "미니게임 봇 종료: 게이지 0개 중 노랑 0개"


# ---------------------------------------------------------------- --cancel-test (AC7)
def test_cancel_test_without_execute_is_an_argparse_error():
    assert bot.main(["--profile", "gpg", "--cancel-test"]) == 2


def test_cancel_test_tip_keeps_moving_then_normal_release(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, sim_s=9.0, cancel_test=True)
    assert r.inj.kinds() == ["press", "cancel", "press", "release"]
    assert r.out.count("취소 점검: 삼각형이 계속 움직여요 (정상)") == 1
    assert r.out.index("취소 점검: 삼각형이 계속 움직여요 (정상)") < r.out.index("게이지 1: 놓음 (지연 60 ms)")
    assert r.loop.m == 1 and r.loop.y == 1
    assert [x["cancel_test"] for x in r.recs] == [False]
    assert r.recs[0]["zone"] == "노랑 (완벽해)"


def test_cancel_test_tip_stopped_warns_and_is_not_counted(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, sim_s=7.0, cancel_test=True, inj_kw={"cancel_stops": True})
    assert r.inj.kinds() == ["press", "cancel"]
    assert "⚠ 취소 점검: 취소했는데 삼각형이 멈췄어요" in r.out
    assert r.loop.m == 0 and r.loop.y == 0
    assert [x["cancel_test"] for x in r.recs] == [True]
    assert not any("결과" in line for line in r.out)
    assert not r.lat_file.exists()                          # no latency sample either


# ---------------------------------------------------------------- records, strips, latency (AC5)
def test_records_strips_and_latency_file(tmp_path, monkeypatch):
    replaced = []
    real_replace = bot.os.replace
    monkeypatch.setattr(bot.os, "replace", lambda a, b: (replaced.append((Path(a), Path(b))), real_replace(a, b))[1])
    r = run(tmp_path, monkeypatch)
    rec = r.recs[0]
    for key in ("ts", "profile", "execute", "n", "bar", "yellow", "period_s", "fit_rms", "frame_period_s",
                "planned_frame_t", "release_sent_t", "latency_used", "latency_sample", "stop_u", "zone",
                "manual", "error_ms"):
        assert key in rec, key
    assert rec["profile"] == "gpg" and rec["execute"] is True and rec["n"] == 1 and rec["manual"] is False
    assert rec["zone"] == "노랑 (완벽해)" and abs(rec["error_ms"]) < 25
    assert rec["period_s"] == pytest.approx(1.0, abs=0.01) and rec["frame_period_s"] == pytest.approx(1 / 60, abs=1e-4)
    assert rec["yellow"][0] == pytest.approx(0.485, abs=0.004)
    strip = tmp_path / "strips" / "S_gpg_g1.png"
    assert strip.exists() and strip.read_bytes()[:4] == b"\x89PNG"
    path, f = bot.claim_file(tmp_path / "strips", "S_gpg_g1")       # an existing name is never overwritten
    f.close()
    assert path.name == "S_gpg_g1_2.png" and strip.stat().st_size > 0
    data = json.loads(r.lat_file.read_text(encoding="utf-8"))
    assert len(data["samples"]) == 1 and data["samples"][0] == pytest.approx(0.06, abs=0.02)
    assert data["method"] == "postmessage" and data["updated"]
    assert replaced == [(r.lat_file.with_name(r.lat_file.name + ".tmp"), r.lat_file)]
    assert not r.lat_file.with_name(r.lat_file.name + ".tmp").exists()


def test_covered_game_writes_no_strip(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch, execute=False, sim_s=5.0, manual_stop_s=3.6, src_kw={"covered": True})
    assert r.recs and not (tmp_path / "strips").exists()


def test_latency_file_with_other_input_method_is_ignored(tmp_path):
    p = tmp_path / "latency_ld.json"
    p.write_text(json.dumps({"samples": [0.1, 0.12], "updated": "x", "method": "swipe"}), encoding="utf-8")
    assert bot.load_latency(p, "ld", "sendevent").samples == []
    assert bot.load_latency(p, "ld", "swipe").samples == [0.1, 0.12]
    assert bot.load_latency(p, "ld", None).samples == [0.1, 0.12]
    assert bot.load_latency(tmp_path / "none.json", "ld").estimate() == 0.2


def test_result_texts_use_the_r8_zone_names():
    assert bot.ZONE_NAMES == {"yellow": "노랑 (완벽해)", "purple": "보라 (쿨)", "blue": "파랑 (나이스)", "outside": "바깥"}
    assert bot.ZONE_UNKNOWN == "판정 불가"
    assert bot.RESULT.format(n=2, zone=bot.ZONE_NAMES["purple"], y=1, m=2) == "게이지 2 결과: 보라 (쿨) · 누적 노랑 1/2"


def test_precise_sleep_lands_within_2_ms():
    clock = VClock()
    slept = []
    target = clock.now + 0.5
    bot.precise_sleep(target, clock, lambda dt: (slept.append(dt), clock.sleep(dt)))
    assert slept and slept[0] == pytest.approx(0.497, abs=0.001)
    assert 0 <= clock.now - target < 0.002


# ---------------------------------------------------------------- replay gate (AC6)
@pytest.mark.skipif(not REC.exists(), reason=f"recording {REC} is not on this machine")
def test_replay_gate_on_recording():
    import cv2
    traces = json.loads(TRACES.read_text(encoding="utf-8"))["gauges"]
    video = bot.VideoSource(cv2, REC)
    out = []
    loop = bot.GaugeLoop(video, bot.NullInjector("gpg"), clock=video.clock, sleeper=video.sleep, profile="gpg",
                         execute=False, replay=True, out=out.append,
                         latency_cal=bot.LatencyCal(default=bot.DEFAULT_LATENCY["gpg"]))
    assert loop.run() == 0
    video.close()
    assert loop.n == 8                                         # all eight recorded gauges, none twice
    verified = 0
    for e in loop.replay_log:
        frame = e["frame_t"] * 60
        k = str(e["n"])                                        # gauges are confirmed in recording order
        stop = traces[k]["stop_frame"]
        if e["zone"] is None:
            assert frame > stop - 1, f"gauge {k}: planned frame {frame:.1f} lies before the stop {stop} but was not read"
        else:
            verified += 1
            assert e["zone"] == "노랑 (완벽해)", f"gauge {k}: planned frame {frame:.1f} reads {e['zone']}"
    assert verified >= 1
    assert out[-1] == f"리플레이: 게이지 8개, 계획한 프레임이 노랑 {verified}개, 확인 불가 {len(loop.replay_log) - verified}개"
    assert sum("[드라이런]" in line for line in out) >= verified
