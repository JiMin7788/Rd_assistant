"""Minigame (군밀 대청소) release planning: sweep model, frame clock, planner, latency calibration.

Pure numpy, no I/O. The tip of the triangle sweeps the bar as a triangle wave in u; the input
registers on mouse UP, one tip position is drawn per game frame, so the bot fits the wave from
timestamped tip reads, picks a future game frame whose predicted tip lies inside yellow with margin
and sends UP `latency` before that frame.

Model: u(t) = lo + (hi - lo) * tri((t - phase) / period), tri(x) = 1 - |2 frac(x) - 1|
(phase = a time at which the tip is at lo going up). fit() is a deterministic least-squares search
(closed-form lo/span for every trial period and phase, then nested grid refinement), no scipy.

Gates (spec R4): fit() is None until a high and a low turning point were seen, >= 1.5 periods are
observed and rms <= 0.6 % of travel. A start-up transient (the bar zooms in and the tip settles
in the first 0.1-0.4 s of a gauge) is cut off: samples up to the last residual > TRANSIENT_FRAC of
travel (or 4 robust sigma of the late residuals) in the first half are ignored, and the gates
count only the remaining samples.

Easing check (tests/fixtures/rdf05/traces.json, all 8 recorded gauges, fit on the settled part):
  The motion is linear right up to the bounces: the bar is a plain triangle wave, no easing. Residual
  of the fit (percent of travel, samples after the first 0.4 s) is rms 0.02 % / max <= 0.07 % in
  the middle and rms 0.04-0.05 % / max <= 0.14 % within 10 % of the range of either end; the turning
  values lie 0.1-2.1 % of travel beyond the highest/lowest sample (the peak falls between two
  frames; fast sweeps move 3.1 % per frame). Only the first 0.1-0.4 s of a gauge (bar zoom-in, tip
  settling) deviates, by up to 3.0 / 2.7 / 5.1 / 3.9 % (gauges 1 / 3 / 5 / 7; gauges 6 and 8 start
  clean, max 0.05 %), so no end part is dropped and the transient is trimmed instead.

Prediction gate (tests/test_minigame_policy.py::test_prediction_gate): fit on the samples up to the
first moment fit() is not None (>= 1.5 periods), predict every later sample up to the user's stop.
Error = |u_at(t) - recorded tip| / travel. Gauges with >= 2.5 periods before the stop:
  gauge  periods  period s  fit at    rms (% travel)  predicted  median   p95    max   (% of travel)
    1     4.72     0.767    1.70 P       0.03            139     0.027  0.073  0.108
    3     7.72     0.767    1.70 P       0.04            277     0.060  0.134  0.163
    7     2.69     0.900    1.59 P       0.05             59     0.031  0.074  0.110
    8     2.73     0.933    1.50 P       0.03             68     0.016  0.054  0.099
  Gauges 5 (2.24 periods), 6 (1.85) and 2, 4 (< 1.5 periods, no fit) are below the 2.5-period bar;
  5 and 6 predict with median 0.019 / 0.012 %, p95 0.043 / 0.035 % when run anyway.

Latencies are calibration, not learning (Hard Rule R3): LatencyCal keeps the last samples
(UP send time -> time the stopped position was on screen, capture clock) and uses their median.
DEFAULT_LATENCY values are unverified starting guesses (spec R7).
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np

DEFAULT_LATENCY = {"gpg": 0.060, "ld": 0.200}
SAFETY = 0.10                 # s kept between "now" and the first action of a release

MIN_SAMPLES = 12
MIN_PERIODS = 1.5             # observed duration / period needed before fit() answers
MAX_RMS_FRAC = 0.006          # rms / travel
TRANSIENT_FRAC = 0.005        # residual / travel (at least) that marks a start-up transient sample
LATENCY_MAX = 0.5
LATENCY_WINDOW = 7


def _tri(x):
    f = x - np.floor(x)
    return 1.0 - np.abs(2.0 * f - 1.0)


@dataclass(frozen=True)
class Fit:
    lo: float
    hi: float
    period: float
    phase: float
    rms: float

    def u_at(self, t):
        return self.lo + (self.hi - self.lo) * _tri((np.asarray(t, float) - self.phase) / self.period)

    def times_at(self, u, t_from, t_to):
        """Sorted times in [t_from, t_to] at which the model tip is at u (empty when u is off the bar)."""
        w = (u - self.lo) / (self.hi - self.lo)
        if not 0.0 <= w <= 1.0 or t_to < t_from:
            return np.empty(0)
        xs = np.unique([w / 2.0, 1.0 - w / 2.0])
        n = np.arange(np.floor((t_from - self.phase) / self.period) - 1,
                      np.ceil((t_to - self.phase) / self.period) + 2)
        ts = (self.phase + self.period * (n[:, None] + xs[None, :])).ravel()
        return np.sort(ts[(ts >= t_from) & (ts <= t_to)])


def _search(t, u, p0):
    """(period, phase, lo, span, mse) minimising the squared error of a triangle wave on (t, u)."""
    tt = t - t[0]
    um = u.mean()
    uv = ((u - um) ** 2).mean()

    def score(period, phases):
        w = _tri((tt[None, :] - phases[:, None]) / period)
        wm = w.mean(1)
        wc = w - wm[:, None]
        var = (wc ** 2).mean(1)
        cov = (wc * (u - um)[None, :]).mean(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            span = cov / var
            mse = uv - cov ** 2 / var
        mse = np.where((var > 1e-12) & (span > 0), mse, np.inf)
        return mse, span, um - span * wm

    best = (np.inf, p0, 0.0, 0.0, 0.0)
    dp = 0.2 * p0 / 60
    for period in p0 * np.linspace(0.9, 1.1, 61):
        phases = np.linspace(0.0, period, 241, endpoint=False)
        mse, span, lo = score(period, phases)
        i = int(np.argmin(mse))
        if mse[i] < best[0]:
            best = (mse[i], period, phases[i], lo[i], span[i])
    dph = best[1] / 240
    for _ in range(9):
        _, pb, phb, _, _ = best
        for period in pb + dp * np.linspace(-1, 1, 11):
            phases = phb + dph * np.linspace(-1, 1, 21)
            mse, span, lo = score(period, phases)
            i = int(np.argmin(mse))
            if mse[i] < best[0]:
                best = (mse[i], period, phases[i], lo[i], span[i])
        dp /= 3.0
        dph /= 3.0
    mse, period, phase, lo, span = best
    return period, phase, lo, span, mse


def _fit_from(t, u):
    """(period, phase, lo, span, rms) of the triangle wave on (t, u), or None (turns missing, too few samples)."""
    if t.size < MIN_SAMPLES:
        return None
    hi_turns, lo_turns = _turns(u)
    if hi_turns < 1 or lo_turns < 1:
        return None
    rng = float(u.max() - u.min())
    dt, du = np.diff(t), np.abs(np.diff(u))
    ok = (dt > 0) & (du > 0)
    if rng <= 0 or not ok.any():
        return None
    speed = float(np.median(du[ok] / dt[ok]))
    period, ph, lo, span, mse = _search(t, u, 2.0 * rng / speed)
    phase = t[0] + (ph % period)
    return period, phase, lo, span, float(np.sqrt(max(mse, 0.0)))


def _turns(u):
    """(high turns, low turns): sign changes of the tip's moving steps (stopped steps are skipped)."""
    d = np.diff(u)
    if d.size == 0:
        return 0, 0
    d = d[np.abs(d) > 0.25 * np.median(np.abs(d)) + 1e-9]
    s = np.sign(d)
    return int(np.sum((s[:-1] > 0) & (s[1:] < 0))), int(np.sum((s[:-1] < 0) & (s[1:] > 0)))


class SweepModel:
    """Collects (t, u) tip reads of one gauge and fits the triangle wave."""

    def __init__(self):
        self.t = []
        self.u = []

    def add(self, t, u):
        if np.isfinite(t) and np.isfinite(u):
            self.t.append(float(t))
            self.u.append(float(u))

    def fit(self):
        """Fit | None: None until both ends were seen, >= 1.5 periods are observed and rms is small."""
        t, u = np.asarray(self.t), np.asarray(self.u)
        order = np.argsort(t, kind="stable")
        t, u = t[order], u[order]
        start = 0
        for it in range(4):
            got = _fit_from(t[start:], u[start:])
            if got is None:
                return None
            period, phase, lo, span, rms = got
            res = np.abs(u[start:] - (lo + span * _tri((t[start:] - phase) / period)))
            thr = max(TRANSIENT_FRAC * span, 4.0 * 1.4826 * float(np.median(res[res.size // 2:])))
            bad = np.flatnonzero(res > thr)
            # AI-NOTE: only a bad stretch in the first half counts as the start-up transient;
            # scattered bad samples (noise) stay in the data and fail the rms gate instead.
            if it < 3 and bad.size and bad[-1] < t[start:].size // 2:
                start += int(bad[-1]) + 1
                continue
            break
        if t[-1] - t[start] < MIN_PERIODS * period or rms > MAX_RMS_FRAC * span:
            return None
        return Fit(lo=float(lo), hi=float(lo + span), period=float(period), phase=float(phase), rms=rms)


def frame_clock(times_moved):
    """(frame_period, frame_phase) of the game's frame instants from capture times at which the tip moved.

    Frame instants are phase + k * period. None when fewer than 4 times are given.
    """
    ts = np.sort(np.asarray(times_moved, float))
    if ts.size < 4:
        return None
    d = np.diff(ts)
    d = d[d > 1e-4]
    if d.size == 0:
        return None
    # AI-NOTE: capture may skip frames, so most gaps are one frame and some are 2-3; the
    # shortest gaps (10th percentile cut) give the one-frame length for the rounding below.
    p0 = float(np.median(d[d <= 1.5 * np.percentile(d, 10)]))
    period = p0
    for _ in range(2):
        k = np.round((ts - ts[0]) / period)
        if np.ptp(k) < 1:
            return None
        a, b = np.polyfit(k, ts, 1)
        period = float(a)
    return period, float(b % period)


def lead_min(press_lead, latency, start_delay=0.0, safety=SAFETY):
    """Shortest time from now to the stop frame: press lead + adb start delay + latency + safety."""
    return press_lead + start_delay + latency + safety


@dataclass(frozen=True)
class Plan:
    frame_t: float        # game frame at which the stopped tip is drawn
    release_t: float      # when to send UP
    margin: float         # u distance from the predicted tip to the nearer yellow edge
    predicted_u: float


def plan_release(fit, frame_clock, yellow, now, latency, *, lead_min,
                 horizon_periods=6, min_margin_frac=0.15):
    """Plan | None: the game frame with the largest in-yellow margin among frames >= now + lead_min.

    Frames are searched from now + lead_min over horizon_periods sweep periods. A frame earlier
    than now + lead_min is never returned (its DOWN / swipe would lie in the past). None when the
    best margin is below min_margin_frac x yellow width or no frame is in yellow.
    """
    if fit is None or frame_clock is None:
        return None
    fp, fph = frame_clock
    y0, y1 = yellow
    t_min = now + lead_min
    t_max = t_min + horizon_periods * fit.period
    k = np.arange(np.ceil((t_min - fph) / fp - 1e-9), np.floor((t_max - fph) / fp) + 1)
    if k.size == 0:
        return None
    ft = fph + k * fp
    u = fit.u_at(ft)
    margin = np.minimum(u - y0, y1 - u)
    if margin.max() < min_margin_frac * (y1 - y0):    # also covers "no frame in yellow" (margin < 0)
        return None
    i = int(np.argmax(margin >= margin.max() - 1e-12))     # earliest among equal margins
    return Plan(frame_t=float(ft[i]), release_t=float(ft[i] - latency),
                margin=float(margin[i]), predicted_u=float(u[i]))


@dataclass
class LatencyCal:
    """Median of the last LATENCY_WINDOW end-to-end latency samples; the default until one arrives."""
    default: float = DEFAULT_LATENCY["gpg"]
    samples: list = field(default_factory=list)

    def add(self, sample):
        if sample is None or not 0.0 <= sample <= LATENCY_MAX:
            return False
        self.samples.append(float(sample))
        return True

    def estimate(self):
        if not self.samples:
            return self.default
        return float(np.median(self.samples[-LATENCY_WINDOW:]))


def latency_sample(fit, stop_u, release_sent_t):
    """Latency in s: when the model tip was at stop_u (first time from 30 ms before UP was sent) - UP send time.

    None when the stopped position is not on the model's bar. A negative result is possible
    (frame quantisation) and is dropped by LatencyCal.add.
    """
    ts = fit.times_at(stop_u, release_sent_t - 0.03, release_sent_t + LATENCY_MAX + 0.1)
    if ts.size == 0:
        return None
    return float(ts[0] - release_sent_t)


def error_ms(fit, yellow, stop_t):
    """Signed timing error of a stop in ms: stop_t - (nearest time the tip crosses the yellow centre).

    Negative = stopped early, positive = late; 0 = exactly at the yellow centre.
    """
    c = 0.5 * (yellow[0] + yellow[1])
    ts = fit.times_at(c, stop_t - fit.period, stop_t + fit.period)
    if ts.size == 0:
        return None
    return float((stop_t - ts[np.argmin(np.abs(ts - stop_t))]) * 1000.0)
