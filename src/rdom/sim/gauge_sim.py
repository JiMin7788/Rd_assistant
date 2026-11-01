"""Gauge simulation harness: a regression check of OUR OWN model of the 군밀 대청소 game.

This is NOT evidence about the real game (spec R11). It encodes what we assume: the tip is a triangle wave
drawn on a game frame clock, an UP stops it at the first game frame at or after its arrival (sent time +
latency + jitter), the capture sees a frame `capture_delay` after it is drawn. Real input-to-frame behaviour,
the real latency range and the cancel path are compared with these assumptions by a human in H5 step 2
(warm-up error_ms / latency range vs the numbers below, `--cancel-test`).

What runs for real: tools/minigame_bot.GaugeLoop with perception.minigame.read_gauge / read_tip and
policy.minigame.lead_min / plan_release / SweepModel / LatencyCal (no reimplementation). What is simulated: a
virtual clock + sleeper, a game (SimGame), the frame source (SimSource) and the input (SimInjector). The sim
starts every case from a fresh LatencyCal with a wrong latency guess; the loop has to converge by itself.

Pieces: SimGame (frame clock at a random phase, triangle-wave tip, one gauge after another, a new gauge ~1 s
after each result, a "user" stop after TIMEOUT_S if the bot never releases), SimSource (GaugeLoop source
interface, synthetic full and band frames the real recognizer reads), SimInjector (press / release / cancel /
release_swipe / press_lead / start_delay / uses_swipe; logs planned / scheduled / sent time of every action),
VirtualClock, run_case(). The truth of a gauge (zone of the tip on the stop frame) comes from the game, never
from the bot's own reading.

Hit rates (python tools/minigame_sim.py --case C --gauges N --seed S; yellow among ALL N gauges, gauges that
got no release count as they ended; capture_delay 0.03 s; the 98 % gate is only on the gpg case in
tests/test_minigame_sim.py, the rest is recorded, not gated):
  gpg        --gauges 104 --seed 1   노랑 103/104 (99 %)   (gated: >= 98 of gauges 5..104)
  ld60       --gauges  40 --seed 1   노랑  22/40  (55 %)   latency estimate 176 ms (sim 150 ms, start 200 ms)
  ld30       --gauges  40 --seed 1   노랑  26/40  (65 %)   latency estimate 200 ms
  ld60swipe  --gauges  40 --seed 1   노랑  13/40  (32 %)   latency estimate 182 ms
Cause of the LD numbers: the assumed input jitter (+-25 ms, and +-30 ms swipe start jitter) is larger than a game
frame (16.7 ms at 60 fps), so the UP lands on the planned frame or a neighbour at random; the loop cannot know it.
These are our assumptions, not measurements; the user decides what LD is worth after H5.

Found by this sim (fixed in tools/minigame_bot.py, AIM_FRAC): the latency median settled where the UP arrives
just before the frame, so GPG gauges slipped a frame (91/100 yellow on this seed). The loop now aims a quarter
frame earlier and takes that off the sample again.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

W, H = 622, 1116                       # canonical content size: the recognizer does not rescale it
COL = {"blue": (77, 154, 253), "purple": (171, 77, 251), "yellow": (250, 210, 48), "dark": (32, 24, 49),
       "tri": (253, 0, 97), "green": (35, 239, 190)}
BAR_Y, TRI_Y, BTN_Y = (610, 630), (634, 658), (760, 840)
BTN_U = (0.30, 0.70)
PURPLE_W = 0.10                        # purple band beside yellow on each side (u)
FIRST_START_S = 0.5


def _px(u):
    return int(round(u * W))


def _tri(x):
    f = x - math.floor(x)
    return 1.0 - abs(2.0 * f - 1.0)


def _crop(frame, region_uv):
    """Same pixel rounding as LiveGrabber.grab_fresh (content-normalised box -> pixel slice)."""
    if region_uv is None:
        return frame
    h, w = frame.shape[:2]
    u0, v0, u1, v1 = region_uv
    x0, y0 = max(0, int(round(u0 * w))), max(0, int(round(v0 * h)))
    x1, y1 = min(w, int(round(u1 * w))), min(h, int(round(v1 * h)))
    return frame[y0:y1, x0:x1]


class VirtualClock:
    """Virtual clock: every call moves it 20 us, so a spin loop terminates. `sleep` is the sleeper."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        self.now += 2e-5
        return self.now

    def sleep(self, dt):
        if dt > 0:
            self.now += dt


@dataclass
class _Gauge:
    idx: int
    t_start: float
    k_start: int                       # first game frame that shows the gauge
    period: float
    yc: float
    yw: float
    stop_k: object = None
    manual: bool = False


class SimGame:
    """The game: frame clock phase + triangle-wave tips of consecutive gauges, all in game-frame indices.

    Frame k is drawn at `phase + k / fps` and reaches the capture `capture_delay` later."""
    LO, HI = 0.16, 0.84                # tip travel (u)
    TIMEOUT_S = 8.0                    # the "user" stops a gauge the bot never released
    RESULT_S = 0.8                     # the stopped gauge stays on screen this long
    GAP_S = 1.0                        # next gauge starts ~1 s after the result (+ up to GAP_JITTER_S)
    GAP_JITTER_S = 0.2

    def __init__(self, seed, fps, capture_delay, latency, jitter, speed_range=(1.3, 2.6),
                 yellow_w_range=(0.025, 0.035), t0=1000.0):
        self.rng = random.Random(f"{seed}/game")
        self.input_rng = random.Random(f"{seed}/input")
        self.fps, self.fp = fps, 1.0 / fps
        self.capture_delay, self.latency, self.jitter = capture_delay, latency, jitter
        self.speed_range, self.yellow_w_range = speed_range, yellow_w_range
        self.phase = self.rng.random() * self.fp
        self.gauges = []
        self.results = []              # one dict per finished gauge, in order
        self._new_gauge(t0 + FIRST_START_S)

    # ----- frame clock -----
    def frame_time(self, k):
        return self.phase + k * self.fp

    def k_visible(self, now):
        """Newest game frame the capture can show at `now`."""
        return math.floor((now - self.capture_delay - self.phase) / self.fp)

    def visible_time(self, k):
        return self.frame_time(k) + self.capture_delay

    # ----- gauges -----
    def _new_gauge(self, t_start):
        prev = self.gauges[-1].yc if self.gauges else None
        speed = self.rng.uniform(*self.speed_range)
        yw = self.rng.uniform(*self.yellow_w_range)
        while True:
            yc = self.rng.uniform(0.32, 0.68)
            if prev is None or abs(yc - prev) >= 0.02:       # a new gauge must look different (same_bar)
                break
        k_start = math.ceil((t_start - self.phase) / self.fp)
        self.gauges.append(_Gauge(idx=len(self.gauges) + 1, t_start=t_start, k_start=k_start,
                                  period=2.0 / speed, yc=yc, yw=yw))

    def tip(self, g, k):
        return self.LO + (self.HI - self.LO) * _tri((self.frame_time(k) - g.t_start) / g.period)

    def edges(self, g):
        yl, yr = g.yc - g.yw / 2, g.yc + g.yw / 2
        return [self.LO, yl - PURPLE_W, yl, yr, yr + PURPLE_W, self.HI]

    def zone(self, g, u):
        e = self.edges(g)
        if e[2] <= u <= e[3]:
            return "yellow"
        if e[1] <= u <= e[4]:
            return "purple"
        return "blue" if e[0] <= u <= e[5] else "outside"

    def tick(self, now):
        """The "user" stops a gauge that has run TIMEOUT_S without a release."""
        g = self.gauges[-1]
        if g.stop_k is None and now >= g.t_start + self.TIMEOUT_S:
            self.register_stop(g.t_start + self.TIMEOUT_S, manual=True)

    def register_stop(self, arrival, manual=False):
        """The tip freezes at the first game frame at or after `arrival`; False when nothing was stopped."""
        g = self.gauges[-1]
        if g.stop_k is not None or arrival < self.frame_time(g.k_start):
            return False
        g.stop_k = max(g.k_start, math.ceil((arrival - self.phase) / self.fp - 1e-9))
        g.manual = manual
        u = self.tip(g, g.stop_k)
        zone = self.zone(g, u)
        self.results.append({"n": g.idx, "zone": zone, "yellow": zone == "yellow", "manual": manual,
                             "tip": u, "yellow_centre": g.yc, "yellow_w": g.yw,
                             "off": (u - g.yc) / g.yw,         # miss distance in yellow widths (~ +-1 = a frame off)
                             "stop_t": self.frame_time(g.stop_k)})
        self._new_gauge(self.frame_time(g.stop_k) + self.GAP_S + self.rng.uniform(0.0, self.GAP_JITTER_S))
        return True

    # ----- what is on screen -----
    def content_id(self, k):
        """Identity of the picture of game frame k: (gauge, tip frame), or ('blank', gauge)."""
        g = None
        for cand in reversed(self.gauges):
            if cand.k_start <= k:
                g = cand
                break
        if g is None:
            return ("blank", 0)
        if g.stop_k is None:
            return (g.idx, k)
        if k >= g.stop_k + math.ceil(self.RESULT_S / self.fp):
            return ("blank", g.idx)
        return (g.idx, min(k, g.stop_k))

    def next_change(self, k, until):
        """Capture time of the first frame after k whose picture differs, or None when after `until`."""
        cur = self.content_id(k)
        j = k + 1
        while self.visible_time(j) <= until:
            if self.content_id(j) != cur:
                return self.visible_time(j)
            j += 1
        return None

    def finished(self, now, gauges):
        return len(self.results) >= gauges and now > self.results[gauges - 1]["stop_t"] + 1.0

    _base_key = None
    _base_img = None

    def _base(self, g):
        key = (g.idx,)
        if self._base_key != key:
            img = np.zeros((H, W, 3), np.uint8)
            img[BAR_Y[0]:BAR_Y[1], _px(0.14):_px(0.86)] = COL["dark"]
            e = self.edges(g)
            for name, a, b in zip(("blue", "purple", "yellow", "purple", "blue"), e[:-1], e[1:]):
                img[BAR_Y[0]:BAR_Y[1], _px(a):_px(b)] = COL[name]
            img[BTN_Y[0]:BTN_Y[1], _px(BTN_U[0]):_px(BTN_U[1])] = COL["green"]
            self._base_key, self._base_img = key, img
        return self._base_img

    def render(self, cid):
        if cid[0] == "blank":
            return np.zeros((H, W, 3), np.uint8)
        g = self.gauges[cid[0] - 1]
        img = self._base(g).copy()
        x = _px(self.tip(g, cid[1]))
        img[TRI_Y[0]:TRI_Y[1], x - 12:x + 12] = COL["tri"]
        return img


class SimSource:
    """GaugeLoop source interface on a SimGame; `end_exc` is the exception class that ends the run."""

    def __init__(self, game, clock, gauges, end_exc):
        self.game, self.clock, self.gauges, self.end_exc = game, clock, gauges, end_exc
        self.last_cid = None

    def _begin(self):
        self.game.tick(self.clock.now)
        if self.game.finished(self.clock.now, self.gauges):
            raise self.end_exc()

    def _cid(self):
        return self.game.content_id(self.game.k_visible(self.clock.now))

    def grab(self):
        self._begin()
        self.clock.now += 0.004
        return self.game.render(self._cid())

    def grab_fresh(self, region_uv=None):
        """Next picture the capture has not delivered yet, or (None, now) after 40 ms without one."""
        self._begin()
        deadline = self.clock.now + 0.040
        while True:
            self.game.tick(self.clock.now)
            cid = self._cid()
            if cid != self.last_cid:
                break
            nxt = self.game.next_change(self.game.k_visible(self.clock.now), deadline)
            if nxt is None:
                self.clock.now = deadline
                return None, self.clock.now
            # AI-NOTE: 1 us past the frame's capture time, so float rounding in k_visible cannot map it back
            # to the previous frame (that would loop forever).
            self.clock.now = nxt + 1e-6
        self.last_cid = cid
        t = self.clock.now
        self.clock.now += 0.0005
        return _crop(self.game.render(cid), region_uv), t

    def unobscured(self):
        return True

    def window_moved(self):
        return False

    def close(self):
        pass


class SimInjector:
    """Input side of the sim: GaugeLoop's injector interface plus an action log.

    UP arrival = sent + game.latency + U(-jitter, +jitter). Swipe fallback: the swipe's UP lands
    start_delay + U(-start_jitter, +start_jitter) + press_lead after the spawn (the loop only knows the
    nominal start_delay()). Every action is logged with the time its plan was made, the time it was
    scheduled for and the time it was sent (virtual clock); `probe` supplies the first two."""

    def __init__(self, game, clock, *, press_lead, start_delay=0.0, start_jitter=0.0, uses_swipe=False,
                 probe=None):
        self.game, self.clock = game, clock
        self.press_lead = press_lead
        self._start_delay, self.start_jitter = start_delay, start_jitter
        self.uses_swipe = uses_swipe
        self.probe = probe
        self.actions = []
        self._down = False

    def start_delay(self):
        return self._start_delay if self.uses_swipe else 0.0

    def _log(self, kind, scheduled, sent):
        planned = self.probe.planned_at if self.probe else None
        self.actions.append({"kind": kind, "planned": planned, "scheduled": scheduled, "sent": sent})

    def _scheduled(self):
        return self.probe.take_target() if self.probe else None

    def _arrive(self, sent, extra=0.0):
        j = self.game.input_rng.uniform(-self.game.jitter, self.game.jitter)
        self.game.register_stop(sent + extra + self.game.latency + j)

    def press(self, u, v, clamp=None):
        self._down = True
        if self.uses_swipe:              # a swipe cannot be held: release_swipe is the whole gesture
            return self.clock.now
        sent = self.clock.now
        self._log("down", self._scheduled(), sent)
        return sent

    def release(self):
        if not self._down or self.uses_swipe:
            return None
        self._down = False
        sent = self.clock.now
        self._log("up", self._scheduled(), sent)
        self._arrive(sent)
        return sent

    def cancel(self):
        """A cancelled press is dragged off the button: nothing reaches the game."""
        if not self._down:
            return None
        self._down = False
        sent = self.clock.now
        self._log("cancel", self._scheduled(), sent)
        return sent

    def release_swipe(self, t_release, clock, sleeper):
        spawn_at = t_release - self.start_delay() - self.press_lead
        now = clock()
        if not self._down or now > spawn_at:
            return None
        sleeper(spawn_at - now)
        self._down = False
        sent = self.clock.now
        self._log("spawn", spawn_at, sent)
        real_start = self._start_delay + self.game.input_rng.uniform(-self.start_jitter, self.start_jitter)
        self._arrive(sent, extra=real_start + self.press_lead)
        return clock()


class Probe:
    """Records, around the real GaugeLoop, when a plan was made and what the loop scheduled.

    AI-NOTE: patches `plan_release` (planned_at = its `now`) and `precise_sleep` (its target = the scheduled
    time of the DOWN, then of the UP) in the minigame_bot module for the length of a run, and calls the
    real functions; the loop is not changed."""

    def __init__(self, bot):
        self.bot = bot
        self.planned_at = None
        self.targets = []

    def take_target(self):
        return self.targets.pop(0) if self.targets else None

    def __enter__(self):
        bot = self.bot
        self._plan, self._sleep = bot.plan_release, bot.precise_sleep

        def plan(fit, fc, yellow, now, latency, **kw):
            self.planned_at = now
            return self._plan(fit, fc, yellow, now, latency, **kw)

        def sleep(t_target, clock, sleeper=None):
            self.targets.append(t_target)
            return self._sleep(t_target, clock, sleeper) if sleeper is not None else self._sleep(t_target, clock)

        bot.plan_release, bot.precise_sleep = plan, sleep
        return self

    def __exit__(self, *exc):
        self.bot.plan_release, self.bot.precise_sleep = self._plan, self._sleep
        return False


@dataclass(frozen=True)
class Case:
    name: str
    profile: str
    fps: float
    press_lead: float
    latency: float
    jitter: float
    guess: float                       # the LatencyCal start value: deliberately wrong
    swipe: bool = False
    start_delay: float = 0.0
    start_jitter: float = 0.0
    capture_delay: float = 0.03        # assumption: the capture shows a frame ~2 frames after it is drawn


CASES = {
    "gpg": Case("gpg", "gpg", 60.0, 0.25, 0.045, 0.003, 0.060),
    "ld60": Case("ld60", "ld", 60.0, 0.6, 0.150, 0.025, 0.200),
    "ld30": Case("ld30", "ld", 30.0, 0.6, 0.150, 0.025, 0.200),
    "ld60swipe": Case("ld60swipe", "ld", 60.0, 0.6, 0.150, 0.025, 0.200, swipe=True,
                      start_delay=0.080, start_jitter=0.030),
}


@dataclass
class SimRun:
    case: Case
    results: list
    actions: list
    cal: object
    code: int
    out: list = field(default_factory=list)

    def yellow(self, first=1, last=None):
        """Yellow count among game gauges first..last (1-based, inclusive)."""
        return sum(r["yellow"] for r in self.results[first - 1:last])


def run_case(bot, case, gauges, seed, *, refit_s=None):
    """Run `gauges` gauges of `case` through the real GaugeLoop (`bot` = the tools/minigame_bot module).

    `refit_s` overrides bot.REFIT_S for the run (a fit takes real time but no virtual time, so the live
    0.10 s makes the suite slow); None keeps the live value."""
    c = case if isinstance(case, Case) else CASES[case]
    clock = VirtualClock()
    game = SimGame(seed, c.fps, c.capture_delay, c.latency, c.jitter, t0=clock.now)
    src = SimSource(game, clock, gauges, bot.EndOfSource)
    probe = Probe(bot)
    inj = SimInjector(game, clock, press_lead=c.press_lead, start_delay=c.start_delay,
                      start_jitter=c.start_jitter, uses_swipe=c.swipe, probe=probe)
    cal = bot.LatencyCal(default=c.guess)
    out = []
    old_refit = bot.REFIT_S
    if refit_s is not None:
        bot.REFIT_S = refit_s
    try:
        with probe:
            loop = bot.GaugeLoop(src, inj, clock=clock, sleeper=clock.sleep, profile=c.profile, execute=True,
                                 latency_cal=cal, out=out.append)
            code = loop.run()
    finally:
        bot.REFIT_S = old_refit
    return SimRun(case=c, results=game.results[:gauges], actions=inj.actions, cal=cal, code=code, out=out)
