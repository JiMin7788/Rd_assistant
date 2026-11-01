"""Minigame gauge bot (군밀 대청소): stop the triangle on yellow by pressing 멈춰 early and releasing on time.

    python tools/minigame_bot.py --profile gpg                 dry run on the live window (no input)
    python tools/minigame_bot.py --profile gpg --execute       real input (the 멈춰 button only)
    python tools/minigame_bot.py --profile gpg --execute --cancel-test   warm-up: check cancel() once
    python tools/minigame_bot.py --profile ld --probe-input    print the LD release method, exit
    python tools/minigame_bot.py --profile gpg --replay REC.mp4          offline, no window, no input

The user presses 대청소 시작 by hand; the bot only handles the gauges and runs until Ctrl+C.
Exit codes: 0 = Ctrl+C / finished replay, 2 = bad command line, 3 = guard stop or failed start check,
anything else = crash. Importing this module has no side effects; everything runs from main(argv).

States (design.md section 2): WAIT (full grab every ~50 ms) -> CONFIRM (two fresh reads, same_gauge) ->
TRACK (band grabs, SweepModel) -> PLAN -> HOLD (execute) or WOULD (dry run / replay) -> RESULT -> WAIT.

Replay gate (tests/test_minigame_bot.py::test_replay_gate_on_recording, recording
C:/dev/_hub/features/minigame/rec/gpg_20261102_003916.mp4, latency 0, GPG press lead 0.25 s), measured:
  8 gauges found (each once); a plan was reached in 5: gauge 3 (planned frame 4662 = 77.70 s, 216 frames before
  the user's stop) reads 노랑 (완벽해) = 1 of 1 verifiable plans yellow; gauges 5, 6, 7 and 8 planned a frame
  at or after the user's own stop (확인 불가, 4); gauges 1, 2 and 4 got no plan (1: yellow 0.0273 u is narrower
  than one frame step of 0.031 u and the 46-frame sweep repeats the same alignment, no frame has the margin;
  2 and 4: stop before 1.5 periods). Output: "리플레이: 게이지 8개, 계획한 프레임이 노랑 1개, 확인 불가 4개".
  The recording's bar detector misreads the first blue edge for 2-4 frames when the triangle is under it, so a
  gauge is "the same" when bar span and yellow interval agree (same_bar) and a new one is confirmed only after
  the bar span has been still for 0.3 s with a moving tip.
"""
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdom import profile as profiles  # noqa: E402
from rdom.input.inject import PRESS_LEAD_GPG, PRESS_LEAD_LD, method_line  # noqa: E402
from rdom.perception.minigame import read_gauge, read_tip, same_gauge, zone_at  # noqa: E402
from rdom.policy.minigame import (  # noqa: E402
    DEFAULT_LATENCY, LATENCY_WINDOW, LatencyCal, Plan, SweepModel, error_ms, frame_clock,
    latency_sample, lead_min, plan_release)

DATA = ROOT / "data" / "minigame"

# --- console texts (spec R2, R8, R9, R10, design F4); the {names} are str.format fields ---
START_FAIL = "⛔ 시작 점검 실패: {reason}"
START_LINE = "미니게임 봇 시작: {label} · {mode}"
MODE_EXECUTE = "실제 입력"
MODE_DRY = "드라이런 (입력 안 함)"
START_HINT = "대청소 시작은 직접 눌러 주세요. 끝내려면 Ctrl+C"
LATENCY_LINE = "지연 보정: {ms} ms ({source})"
LATENCY_SAVED = "저장값 {n}개"
LATENCY_DEFAULT = "기본값"
WAITING = "게이지 기다리는 중"
RELEASED = "게이지 {n}: 놓음 (지연 {ms} ms)"
WOULD_RELEASE = "게이지 {n}: [드라이런] 여기서 놓았을 거예요"
RESULT = "게이지 {n} 결과: {zone} · 누적 노랑 {y}/{m}"
RESULT_MANUAL = "게이지 {n} 결과 (직접 멈춤): {zone}"
UNREADABLE = "⚠ 게이지 {n}: 삼각형 움직임을 못 읽어서 기다려요"
COVERED_WARN = "⚠ 다른 창이 게임을 가려서 이번엔 안 눌러요"
NOT_REGISTERED = "⚠ 게이지 {n}: 놓았는데 삼각형이 안 멈췄어요 ({k}/3)"
NOT_REGISTERED_STOP = "⛔ 멈춰 입력이 3번 연속 먹히지 않아서 멈춰요"
WINDOW_MOVED = "⛔ 게임 창이 움직여서 멈춰요"
END_LINE = "미니게임 봇 종료: 게이지 {m}개 중 노랑 {y}개"
CANCEL_MOVING = "취소 점검: 삼각형이 계속 움직여요 (정상)"
CANCEL_STOPPED = "⚠ 취소 점검: 취소했는데 삼각형이 멈췄어요"
NO_PROBE_GPG = "GPG는 창 메시지 입력이라 점검할 게 없어요"
REPLAY_AT = "게이지 {n}: 계획한 프레임의 위치 = {zone}"
REPLAY_UNKNOWN = "게이지 {n}: 계획한 프레임 전에 직접 멈춤 (확인 불가)"
REPLAY_END = "리플레이: 게이지 {m}개, 계획한 프레임이 노랑 {y}개, 확인 불가 {u}개"
REPLAY_OPEN_FAIL = "리플레이 파일을 열 수 없어요: {path}"

ZONE_YELLOW = "노랑 (완벽해)"
ZONE_NAMES = {"yellow": ZONE_YELLOW, "purple": "보라 (쿨)", "blue": "파랑 (나이스)", "outside": "바깥"}
ZONE_UNKNOWN = "판정 불가"

EXIT_CLEAN, EXIT_USAGE, EXIT_GUARD = 0, 2, 3

# --- timing (seconds unless noted) ---
WAIT_S = 0.05              # pause between full grabs while no gauge is on screen
STILL_S = 0.25             # tip unchanged this long = stopped
STILL_EPS = 0.002          # u change that counts as "the tip moved" (video noise moves it by < 0.001)
REGISTER_S = 1.0           # tip still moving this long after UP = the release did not register
CANCEL_WATCH_S = 1.0       # --cancel-test: how long the tip is watched after cancel()
GONE_S = 0.5               # no tip read this long -> look at the whole bar again
CHECK_S = 1.0              # full-bar re-check interval while tracking (new gauge / bar gone)
UNREADABLE_S = 10.0        # no plan this long after confirmation -> warn once
PREP_S = 0.16              # go into HOLD when the first action is at most this far away (> SAFETY)
REFIT_S = 0.10             # at most one model refit per this interval (a fit takes 60-120 ms)
NO_REFIT_S = 0.30          # no refit once the first action is this close: keep the plan, stay on time
SPIN_S = 0.003             # precise_sleep spins for the last 3 ms
BAND_V = 0.08              # tip band: from the bar centre this far down (v)
BAND_U = 0.03              # tip band: this much beyond the bar ends (u)
STRIP_V = (0.14, 0.10)     # strip: result text above the bar, triangle and a margin below
REPLAY_TOL = 0.03          # replay: |tip - model| / travel below this = the video still sweeps
CONFIRM_MISSES = 25        # CONFIRM: new-frame timeouts (40 ms each) before falling back to WAIT
SETTLE_S = 0.3             # CONFIRM: the bar span must not have moved for this long (zoom-in animation)
SAME_TOL = 0.004           # bar span / yellow interval tolerance (u), spec R3
HORIZON_PERIODS = 2        # plan_release looks this many sweep periods ahead
AIM_FRAC = 0.25            # UP is aimed this fraction of a game frame earlier than the latency median says
MAX_SUFFIX = 99
PRESS_LEAD = {"gpg": PRESS_LEAD_GPG, "ld": PRESS_LEAD_LD}


class EndOfSource(Exception):
    """The frame source has no more frames (end of a replay video)."""


class _Stop(Exception):
    """A guard stop: `text` is printed, the exit code is 3."""

    def __init__(self, text):
        super().__init__(text)
        self.text = text


def same_bar(a, b, tol=SAME_TOL):
    """True when two reads show the same bar span and yellow interval (spec R3, the new-gauge test).

    AI-NOTE: looser than perception.same_gauge on purpose. On the recording the first blue/purple
    edge is misread for 2-4 frames whenever the triangle sits under it, which would look like a
    new gauge several times per sweep; the bar ends and the yellow edges stay put."""
    if a is None or b is None:
        return False
    return all(abs(x - y) <= tol for x, y in
               zip((*a.bar, *a.yellow), (*b.bar, *b.yellow)))


def precise_sleep(t_target, clock, sleep=time.sleep):
    """Wait until clock() >= t_target: sleep down to 3 ms before it, then spin."""
    coarse = t_target - clock() - SPIN_S
    if coarse > 0:
        sleep(coarse)
    while clock() < t_target:
        pass


def claim_file(folder, stamp):
    """Create `<stamp>.png`, else `<stamp>_2.png` ... `_99.png`, by exclusive create ('xb').

    Same rule as tools/save_frame.claim_file (that module is a script, not importable from the
    tests). Returns (path, open binary file) or None when every name is taken."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_SUFFIX + 1):
        path = folder / (f"{stamp}.png" if n == 1 else f"{stamp}_{n}.png")
        try:
            return path, open(path, "xb")
        except FileExistsError:
            continue
    return None


def load_latency(path, profile, method=None):
    """LatencyCal from `path`; the profile default when there is no usable file.

    `method` (postmessage / sendevent / swipe): a file written with another input method is
    ignored, its latencies do not apply. None = accept any (dry run, which writes nothing)."""
    cal = LatencyCal(default=DEFAULT_LATENCY[profile])
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if method is not None and data.get("method") != method:
            return cal
        for s in data.get("samples", []):
            cal.add(s)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return cal


def save_latency(path, cal, method):
    """Write {samples, updated, method} atomically: temp file next to it, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"samples": [round(s, 5) for s in cal.samples[-LATENCY_WINDOW:]],
            "updated": datetime.now().isoformat(timespec="seconds"), "method": method}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class NullInjector:
    """Replay injector: carries the profile's press lead, sends nothing."""
    uses_swipe = False

    def __init__(self, profile):
        self.press_lead = PRESS_LEAD[profile]

    def start_delay(self):
        return 0.0

    def press(self, u, v, clamp=None):
        return None

    def release(self):
        return None

    def cancel(self):
        return None

    def release_swipe(self, t_release, clock, sleeper):
        return None


def _crop(frame, region_uv):
    """Crop `frame` to a content-normalised box with LiveGrabber.grab_fresh's rounding."""
    if region_uv is None:
        return frame
    h, w = frame.shape[:2]
    u0, v0, u1, v1 = region_uv
    x0, y0 = max(0, int(round(u0 * w))), max(0, int(round(v0 * h)))
    x1, y1 = min(w, int(round(u1 * w))), min(h, int(round(v1 * h)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty region {region_uv} in {w}x{h}")
    return frame[y0:y1, x0:x1]


class VideoSource:
    """Frame source over a recorded video (replay): time t = frame index / fps, never a window."""

    def __init__(self, cv2_mod, path):
        self.cv2 = cv2_mod
        self.cap = cv2_mod.VideoCapture(str(path))
        self.fps = float(self.cap.get(cv2_mod.CAP_PROP_FPS) or 0.0) if self.cap.isOpened() else 0.0
        frames = self.cap.get(cv2_mod.CAP_PROP_FRAME_COUNT) if self.cap.isOpened() else 0
        if not self.cap.isOpened() or self.fps <= 0 or frames <= 0:
            self.cap.release()
            raise ValueError(f"cannot read video {path}")
        self.idx = -1

    def clock(self):
        return max(self.idx, 0) / self.fps

    def _next(self):
        ok, bgr = self.cap.read()
        if not ok:
            raise EndOfSource()
        self.idx += 1
        return self.cv2.cvtColor(bgr, self.cv2.COLOR_BGR2RGB)

    def sleep(self, dt):
        """The replay's sleeper: skip the frames of `dt` seconds."""
        for _ in range(int(round(dt * self.fps))):
            if not self.cap.grab():
                raise EndOfSource()
            self.idx += 1

    def grab(self):
        return self._next()

    def grab_fresh(self, region_uv=None):
        frame = self._next()
        return _crop(frame, region_uv), self.idx / self.fps

    def window_moved(self):
        return False

    def unobscured(self):
        return True

    def close(self):
        self.cap.release()


@dataclass
class _Gauge:
    n: int
    read: object
    band: tuple                      # region handed to grab_fresh (content-normalised)
    band_box: tuple                  # the same region snapped to whole pixels, handed to read_tip
    t0: float
    model: SweepModel = field(default_factory=SweepModel)
    moved_ts: list = field(default_factory=list)     # capture times at which the tip moved
    ref_u: object = None             # tip u at the last move (= the stop position once it stops)
    last_move_t: object = None
    hold_end_t: object = None
    last_tip_t: object = None
    last_sample_still: bool = False
    fit: object = None
    fit_t: float = float("-inf")
    fc: object = None
    dirty: bool = False
    plan: object = None              # current candidate plan (re-planned on every iteration)
    planned: object = None           # the plan that was sent (execute) or frozen (dry run / replay)
    latency_used: float = 0.0
    aim_used: float = 0.0            # the part of latency_used that is AIM_FRAC, not calibration
    ever_planned: bool = False
    warned_unreadable: bool = False
    warned_covered: bool = False
    next_check: float = 0.0
    would_done: bool = False
    replay_state: object = None
    released_t: object = None
    release_sent_t: object = None
    press_sent_t: object = None
    watch: object = None             # --cancel-test: time cancel() was sent while the watch runs


class GaugeLoop:
    """Wires perception, model, capture and input; see the module docstring for the states."""

    def __init__(self, source, injector, *, clock, sleeper, profile, execute, latency_cal,
                 records=None, strips=None, out=print, latency_file=None, method=None,
                 cancel_test=False, replay=False, stamp=None):
        self.source, self.injector = source, injector
        self.clock, self.sleeper = clock, sleeper
        self.profile, self.execute = profile, execute
        self.cal = latency_cal
        self.records, self.strips = records, strips
        self.out = out
        self.latency_file, self.method = latency_file, method
        self.cancel_pending = bool(cancel_test) and execute
        self.replay = replay
        self.stamp = stamp or (lambda: time.strftime("%Y%m%d_%H%M%S"))
        self.n = 0                   # confirmed gauges
        self.m = self.y = 0          # released and registered / of them yellow
        self.fails = 0               # consecutive unregistered releases
        self.replay_yellow = self.replay_unknown = 0
        self.replay_log = []         # replay: {n, frame_t, zone} per plan that was checked
        self._ended = None           # read of the gauge that just ended: not a new gauge while it stays

    # ----- top level -----
    def run(self):
        """Run until Ctrl+C / guard / end of source; returns the exit code."""
        try:
            while True:
                read, shape = self._wait_confirm()
                self.n += 1
                self._gauge(read, shape)
        except EndOfSource:
            self.out(self._end_line())
            return EXIT_CLEAN
        except KeyboardInterrupt:
            self.injector.cancel()           # AI-NOTE: never a plain release: that would click 멈춰
            self.out(self._end_line())
            return EXIT_CLEAN
        except _Stop as s:
            self.injector.cancel()
            self.out(s.text)
            return EXIT_GUARD
        except BaseException:
            self.injector.cancel()
            raise

    def _end_line(self):
        if self.replay:
            return REPLAY_END.format(m=self.n, y=self.replay_yellow, u=self.replay_unknown)
        return END_LINE.format(m=self.m, y=self.y)

    def _check_window(self):
        if self.source.window_moved():
            raise _Stop(WINDOW_MOVED)

    # ----- WAIT / CONFIRM -----
    def _wait_confirm(self):
        """Block until two consecutive fresh reads give the same bar; returns (read, frame shape)."""
        first = None
        misses = 0
        moved_t = self.clock()       # last time the bar span moved (zoom-in animation)
        prev_bar = None
        while True:
            self._check_window()
            if first is None:
                frame = self.source.grab()
                read = read_gauge(frame)
                if read is None:
                    self._ended = None
                elif not same_bar(read, self._ended):
                    first, misses, moved_t, prev_bar = read, 0, self.clock(), read.bar
                    continue
                self.sleeper(WAIT_S)
                continue
            frame, _ = self.source.grab_fresh(None)
            if frame is None:
                misses += 1
                if misses > CONFIRM_MISSES:
                    first = None
                continue
            misses = 0
            read = read_gauge(frame)
            if read is None:
                first = None
                continue
            now = self.clock()
            if max(abs(read.bar[0] - prev_bar[0]), abs(read.bar[1] - prev_bar[1])) > SAME_TOL:
                moved_t = now
            prev_bar = read.bar
            # AI-NOTE: a bar whose tip stands still is the leftover of a gauge that just ended (its result
            # animation can change the bar), never a live gauge: a live tip moves between two frames.
            if (same_gauge(first, read) and now - moved_t >= SETTLE_S
                    and abs(read.tip_u - first.tip_u) > STILL_EPS):
                return read, frame.shape[:2]
            first = read                 # not confirmed yet: the next read is compared with this one

    # ----- one gauge: TRACK / PLAN / HOLD / WOULD / RESULT -----
    def _new_gauge(self, read, shape):
        h, w = shape
        u0, u1 = max(0.0, read.bar[0] - BAND_U), min(1.0, read.bar[1] + BAND_U)
        v0, v1 = read.v, min(1.0, read.v + BAND_V)
        # AI-NOTE: grab_fresh rounds the box to pixels; read_tip must be told the box actually cut,
        # otherwise the tip u is off by up to half a pixel against the yellow edges.
        px = (int(round(u0 * w)), int(round(v0 * h)), int(round(u1 * w)), int(round(v1 * h)))
        box = (px[0] / w, px[1] / h, px[2] / w, px[3] / h)
        t = self.clock()
        return _Gauge(n=self.n, read=read, band=(u0, v0, u1, v1), band_box=box, t0=t,
                      last_tip_t=t, next_check=t + CHECK_S)

    def _gauge(self, read, shape):
        g = self._new_gauge(read, shape)
        while True:
            self._check_window()
            frame, t = self.source.grab_fresh(g.band)
            new = frame is not None
            u = read_tip(frame, g.band_box) if new else None
            if u is not None:
                self._on_sample(g, t, u)
            stopped = self._still_for(g, t)
            gone = not stopped and self._maybe_gone(g, t)
            if g.watch is not None:                      # --cancel-test watch
                if stopped or gone:
                    self.out(CANCEL_STOPPED)
                    return self._result(g, t, cancel_test=True)
                if t - g.watch >= CANCEL_WATCH_S:
                    self.out(CANCEL_MOVING)
                    g.watch = None
                continue
            if stopped or gone:
                return self._result(g, t, gone=gone)
            if g.released_t is not None:
                if t - g.released_t >= REGISTER_S:
                    self._unregistered(g)
                continue
            if g.planned is None:
                self._plan_step(g)
            if g.planned is not None and not self.execute:
                self._would_step(g, t, new, u)

    def _on_sample(self, g, t, u):
        g.last_tip_t = t
        moved = g.ref_u is None or abs(u - g.ref_u) > STILL_EPS
        g.last_sample_still = not moved
        if moved:
            g.ref_u, g.last_move_t = u, t
            g.model.add(t, u)
            g.moved_ts.append(t)
            g.dirty = True

    def _still_for(self, g, t):
        """True when the tip has not moved for STILL_S as of capture time t."""
        # AI-NOTE: after a HOLD no grabs happened, so last_move_t is cleared there and the time of
        # the hold's end counts until the first move is seen again.
        ref = g.last_move_t if g.last_move_t is not None else g.hold_end_t
        return ref is not None and t - ref >= STILL_S

    def _maybe_gone(self, g, t):
        """True when the bar is gone or replaced by another gauge (checked now and then)."""
        if t - g.last_tip_t < GONE_S and t < g.next_check:
            return False
        g.next_check = t + CHECK_S
        for _ in range(2):
            frame, _ = self.source.grab_fresh(None)
            if frame is None:            # nothing on screen changed: the bar is still there
                return False
            r = read_gauge(frame)
            if r is not None and same_bar(g.read, r):
                g.last_tip_t = t
                return False
        return True                      # AI-NOTE: two bad reads in a row, one could be a glitch

    def _unregistered(self, g):
        self.fails += 1
        self.out(NOT_REGISTERED.format(n=g.n, k=self.fails))
        if self.fails >= 3:
            raise _Stop(NOT_REGISTERED_STOP)
        g.released_t = g.release_sent_t = g.press_sent_t = None
        g.planned = g.plan = None

    # ----- PLAN -----
    def _choose(self, g, now, latency, lead):
        """The planner's answer, but a still-reachable earlier frame stays unless a clearly better one appears."""
        cand = plan_release(g.fit, g.fc, g.read.yellow, now, latency, lead_min=lead,
                            horizon_periods=HORIZON_PERIODS)
        old = g.plan
        if old is not None and old.frame_t >= now + lead - 1e-9:
            y0, y1 = g.read.yellow
            u = float(g.fit.u_at(old.frame_t))
            margin = min(u - y0, y1 - u)
            w = y1 - y0
            if margin >= 0.15 * w and (cand is None or cand.margin <= margin + 0.1 * w):
                return Plan(frame_t=old.frame_t, release_t=old.frame_t - latency,
                            margin=margin, predicted_u=u)
        return cand

    def _plan_step(self, g):
        inj = self.injector
        sd = inj.start_delay()
        now = self.clock()
        first_t = (g.plan.release_t - inj.press_lead - sd) if g.plan is not None else float("inf")
        if g.dirty and now - g.fit_t >= REFIT_S and first_t - now > NO_REFIT_S:
            g.fit, g.fc = g.model.fit(), frame_clock(g.moved_ts)
            g.dirty, g.fit_t = False, now
            now = self.clock()
        if g.fit is None or g.fc is None:
            g.plan = None
            return self._warn_unreadable(g)
        # AI-NOTE: a sample is "stop frame - UP sent" = true latency + the gap between the UP's arrival and
        # that frame (0..1 frame), so the median settles where the UP arrives just before the frame: any
        # input jitter then tips the stop onto the next frame, one frame off = a miss (found by the gauge
        # sim, tests/test_minigame_sim.py), and the median never reacts to the few late stops. Aim a
        # quarter frame earlier; _result takes the same aim off the sample so the estimate does not ramp.
        aim = 0.0 if self.replay else AIM_FRAC * g.fc[0]
        latency = 0.0 if self.replay else self.cal.estimate() + aim
        lead = lead_min(inj.press_lead, latency, sd)
        g.plan = self._choose(g, now, latency, lead)
        if g.plan is None:
            return self._warn_unreadable(g)
        g.ever_planned = True
        g.latency_used, g.aim_used = latency, aim
        first_t = g.plan.release_t - inj.press_lead - sd
        if self.clock() + PREP_S < first_t:
            return None                  # more tracking first: the plan is refined on every frame
        if self.execute:
            return self._hold(g, g.plan, first_t)
        g.planned = g.plan               # dry run / replay: freeze it, WOULD prints at release_t
        return None

    def _warn_unreadable(self, g):
        if not g.ever_planned and not g.warned_unreadable and self.clock() - g.t0 > UNREADABLE_S:
            g.warned_unreadable = True
            self.out(UNREADABLE.format(n=g.n))

    # ----- HOLD -----
    def _hold(self, g, plan, first_t):
        """Press at first_t, release (or cancel, --cancel-test) at plan.release_t. Never a late DOWN."""
        inj = self.injector
        if not self.source.unobscured():
            if not g.warned_covered:
                g.warned_covered = True
                self.out(COVERED_WARN)
            g.plan = None
            return
        if self.clock() > first_t:       # AI-NOTE: a slow grab / check ate the lead: send nothing, re-plan
            g.plan = None
            return
        button = g.read.button
        uv = ((button[0] + button[2]) / 2, (button[1] + button[3]) / 2)
        swipe = bool(getattr(inj, "uses_swipe", False))
        test = self.cancel_pending and not swipe     # a swipe cannot be held, so cancel() has nothing to test
        if swipe:
            inj.press(*uv, clamp=button)             # keeps the point only; the swipe is the press+release
            spawn = inj.release_swipe(plan.release_t, self.clock, self.sleeper)
            if spawn is None:
                g.plan = None
                return
            press_t = spawn
            sent_t = spawn + inj.start_delay() + inj.press_lead     # when the swipe's UP lands
        else:
            precise_sleep(first_t, self.clock, self.sleeper)
            press_t = inj.press(*uv, clamp=button)
            precise_sleep(plan.release_t, self.clock, self.sleeper)
            sent_t = inj.cancel() if test else inj.release()
        end = self.clock()
        if sent_t is None:
            sent_t = end
        g.hold_end_t, g.last_move_t = end, None
        g.plan = None
        self._check_window()
        if test:
            self.cancel_pending = False
            g.watch = sent_t
            return
        g.planned, g.released_t, g.release_sent_t, g.press_sent_t = plan, sent_t, sent_t, press_t
        self.out(RELEASED.format(n=g.n, ms=round((g.latency_used - g.aim_used) * 1000)))   # the calibrated part

    # ----- WOULD (dry run / replay) -----
    def _would_step(self, g, t, new, u):
        plan = g.planned
        half = 0.5 * g.fc[0] if self.replay else 0.0
        if not g.would_done and self.clock() >= plan.release_t - half:
            g.would_done = True
            self.out(WOULD_RELEASE.format(n=g.n))
        if self.replay and g.would_done and g.replay_state is None and new and t >= plan.frame_t - half:
            g.replay_state = "done"
            if u is not None and abs(u - float(g.fit.u_at(t))) <= REPLAY_TOL * (g.fit.hi - g.fit.lo):
                zone = ZONE_NAMES[zone_at(g.read, u)]
                self.out(REPLAY_AT.format(n=g.n, zone=zone))
                self.replay_yellow += zone == ZONE_YELLOW
                self.replay_log.append({"n": g.n, "frame_t": plan.frame_t, "zone": zone})
            else:
                self._replay_unknown(g, plan)

    def _replay_unknown(self, g, plan):
        self.out(REPLAY_UNKNOWN.format(n=g.n))
        self.replay_unknown += 1
        self.replay_log.append({"n": g.n, "frame_t": plan.frame_t, "zone": None})

    # ----- RESULT -----
    def _result(self, g, t, *, gone=False, cancel_test=False):
        # AI-NOTE: a vanished bar only gives a zone when the tip was already standing still.
        stop_u = g.ref_u if g.ref_u is not None and (not gone or g.last_sample_still) else None
        zone = ZONE_UNKNOWN if stop_u is None else ZONE_NAMES[zone_at(g.read, stop_u)]
        by_bot = g.released_t is not None and not cancel_test
        sample = err = None
        if by_bot:
            self.fails = 0               # a registered release resets the failure count
            self.m += 1
            self.y += zone == ZONE_YELLOW
            self.out(RESULT.format(n=g.n, zone=zone, y=self.y, m=self.m))
            if g.fit is not None and stop_u is not None:
                sample = latency_sample(g.fit, stop_u, g.release_sent_t)
                stop_t = g.last_move_t if g.last_move_t is not None else t
                err = error_ms(g.fit, g.read.yellow, stop_t)
                if sample is not None and self.cal.add(sample - g.aim_used) and self.execute and self.latency_file:
                    save_latency(self.latency_file, self.cal, self.method)
        elif not cancel_test:
            self.out(RESULT_MANUAL.format(n=g.n, zone=zone))
        if self.replay:
            pending = g.planned if g.planned is not None else g.plan
            if pending is not None and g.replay_state is None:
                self._replay_unknown(g, pending)
        self._record(g, zone, stop_u, sample, err, manual=not by_bot, cancel_test=cancel_test)
        self._save_strip(g)
        self._ended = g.read

    def _record(self, g, zone, stop_u, sample, err, *, manual, cancel_test):
        if self.records is None:
            return
        fit, plan = g.fit, g.planned
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "profile": self.profile,
               "execute": self.execute, "n": g.n, "bar": list(g.read.bar),
               "yellow": list(g.read.yellow),
               "period_s": fit.period if fit else None, "fit_rms": fit.rms if fit else None,
               "frame_period_s": g.fc[0] if g.fc else None,
               "planned_frame_t": plan.frame_t if plan else None,
               "press_sent_t": g.press_sent_t, "release_sent_t": g.release_sent_t,
               "latency_used": g.latency_used if plan else None, "latency_sample": sample,
               "stop_u": stop_u, "zone": zone, "manual": manual, "error_ms": err,
               "cancel_test": cancel_test}
        path = Path(self.records)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=float) + "\n")

    def _save_strip(self, g):
        """PNG of the gauge band (bar and the result text above it); nothing when the game is covered (R5)."""
        if self.strips is None or not self.source.unobscured():
            return
        frame = self.source.grab()
        h, w = frame.shape[:2]
        v0, v1 = max(0.0, g.read.v - STRIP_V[0]), min(1.0, g.read.v + STRIP_V[1])
        u0, u1 = max(0.0, g.read.bar[0] - BAND_U), min(1.0, g.read.bar[1] + BAND_U)
        crop = frame[int(v0 * h):int(v1 * h), int(u0 * w):int(u1 * w)]
        ok, buf = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
        claimed = claim_file(self.strips, f"{self.stamp()}_{self.profile}_g{g.n}") if ok else None
        if claimed is None:
            return
        with claimed[1] as f:
            f.write(buf.tobytes())


def build_parser():
    ap = argparse.ArgumentParser(
        prog="minigame_bot", description="Stop the 군밀 대청소 triangle on yellow (dry run unless --execute).")
    ap.add_argument("--profile", choices=sorted(profiles.PROFILES), required=True,
                    help="gpg = Google Play Games window, ld = LDPlayer window")
    ap.add_argument("--execute", action="store_true", help="send real input (default: dry run)")
    ap.add_argument("--replay", metavar="PATH", help="run on a recorded video: no window, no input")
    ap.add_argument("--probe-input", action="store_true", help="print the LD release method and exit")
    ap.add_argument("--cancel-test", action="store_true",
                    help="with --execute: on the first planned gauge cancel() instead of releasing")
    return ap


def _seam(seams, name, default):
    return seams[name] if name in seams else default()


def main(argv=None, *, seams=None, out=print):
    """CLI entry. `seams` replaces the outside world in tests: preflight, grabber, injector,
    resolve_device, video (callables), clock, sleeper, data_dir."""
    seams = seams or {}
    ap = build_parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        if a.replay and a.execute:
            ap.error("--replay cannot be combined with --execute")
        if a.cancel_test and not a.execute:
            ap.error("--cancel-test needs --execute")
        if a.probe_input and (a.replay or a.execute):
            ap.error("--probe-input cannot be combined with --replay or --execute")
    except SystemExit as e:
        return int(e.code)
    prof = profiles.get(a.profile)
    cfg = str(ROOT / prof.config)
    data = Path(seams.get("data_dir", DATA))
    if a.replay:
        return _main_replay(a, seams, out)
    if a.probe_input:
        return _main_probe(a, cfg, seams, out)
    return _main_live(a, prof, cfg, data, seams, out)


def _main_replay(a, seams, out):
    try:
        video = _seam(seams, "video", lambda: (lambda p: VideoSource(cv2, p)))(a.replay)
    except ValueError:
        out(REPLAY_OPEN_FAIL.format(path=a.replay))
        return EXIT_USAGE
    try:
        loop = GaugeLoop(video, NullInjector(a.profile), clock=video.clock, sleeper=video.sleep,
                         profile=a.profile, execute=False, replay=True, out=out,
                         latency_cal=LatencyCal(default=DEFAULT_LATENCY[a.profile]))
        return loop.run()
    finally:
        video.close()


def _main_probe(a, cfg, seams, out):
    if a.profile == "gpg":
        out(NO_PROBE_GPG)
        return EXIT_CLEAN
    from rdom.capture import preflight
    if "injector" in seams:
        make = seams["injector"]
    else:
        from rdom.input.inject import make_injector as make
    if "resolve_device" in seams:
        resolve = seams["resolve_device"]
    else:
        from rdom.input.inject import resolve_device as resolve
    inj = make(cfg, False)
    try:
        # AI-NOTE: a dry-run AdbInjector never resolves the adb serial; the read-only probe needs it.
        inj.device = resolve(inj.adb, inj.device)
        method = inj.probe_release_method()
    except RuntimeError:
        out(START_FAIL.format(reason=preflight.NO_ADB))
        return EXIT_GUARD
    out(method_line(method))
    return EXIT_CLEAN


def _main_live(a, prof, cfg, data, seams, out):
    from rdom.capture import preflight
    check = _seam(seams, "preflight", lambda: preflight.check)
    for _, ok, reason in check([a.profile], place=True):
        if not ok:
            out(START_FAIL.format(reason=reason))
            return EXIT_GUARD
    if "grabber" in seams:
        grabber = seams["grabber"](cfg)
    else:
        from rdom.capture.live import LiveGrabber
        grabber = LiveGrabber(cfg)
    try:
        if "injector" in seams:
            inj = seams["injector"](cfg, a.execute)
        else:
            from rdom.input.inject import make_injector
            inj = make_injector(cfg, execute=a.execute)
        method = method_name = None
        if a.execute:
            method_name = "postmessage"
            if a.profile == "ld":
                method = inj.probe_release_method()
                method_name = method[0]
        lat_file = data / f"latency_{a.profile}.json"
        cal = load_latency(lat_file, a.profile, method_name)
        out(START_LINE.format(label=preflight.LABEL[a.profile],
                              mode=MODE_EXECUTE if a.execute else MODE_DRY))
        out(START_HINT)
        out(LATENCY_LINE.format(
            ms=round(cal.estimate() * 1000),
            source=LATENCY_SAVED.format(n=len(cal.samples)) if cal.samples else LATENCY_DEFAULT))
        if method is not None:
            out(method_line(method))
        out(WAITING)
        loop = GaugeLoop(grabber, inj, clock=_seam(seams, "clock", lambda: time.perf_counter),
                         sleeper=_seam(seams, "sleeper", lambda: time.sleep),
                         profile=a.profile, execute=a.execute, latency_cal=cal,
                         records=data / "gauges.jsonl", strips=data / "strips", out=out,
                         latency_file=lat_file if a.execute else None, method=method_name,
                         cancel_test=a.cancel_test)
        return loop.run()
    finally:
        close = getattr(grabber, "close", None)
        if close:
            close()


if __name__ == "__main__":
    sys.exit(main())
