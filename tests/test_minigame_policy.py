"""Tests for policy/minigame.py: sweep fit, frame clock, release planner, latency calibration."""
import ast
import json
import pathlib

import numpy as np
import pytest

from rdom.policy import minigame as mg
from rdom.policy.minigame import (DEFAULT_LATENCY, SAFETY, Fit, LatencyCal, Plan, SweepModel,
                                  error_ms, frame_clock, latency_sample, lead_min, plan_release)

TRACES = pathlib.Path(__file__).parent / "fixtures" / "rdf05" / "traces.json"
FP = 1.0 / 60.0

# (name, press_lead, latency, start_delay) of the three input profiles
PROFILES = [("gpg", 0.25, 0.06, 0.0), ("ld_sendevent", 0.6, 0.2, 0.0), ("ld_swipe", 0.6, 0.2, 0.08)]


def tri_u(t, lo=0.15, hi=0.85, period=0.8, phase=0.0):
    return Fit(lo, hi, period, phase, 0.0).u_at(t)


def sweep(duration, step=FP, t0=0.0, **kw):
    t = t0 + np.arange(0.0, duration, step)
    return t, tri_u(t, **kw)


def fed(t, u):
    m = SweepModel()
    for a, b in zip(t, u):
        m.add(a, b)
    return m


# --- AC1 -------------------------------------------------------------------------------------

def test_module_is_pure():
    tree = ast.parse(pathlib.Path(mg.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module.split(".")[0])
    assert mods <= {"__future__", "dataclasses", "numpy"}


def test_default_latency():
    assert DEFAULT_LATENCY == {"gpg": 0.060, "ld": 0.200}


# --- AC2: prediction gate on the recording ----------------------------------------------------

def _gauge_series(v):
    return [(t, u) for t, u in v["series"] if t <= v["stop_t"] + 1e-6]


def test_prediction_gate():
    gauges = json.loads(TRACES.read_text())["gauges"]
    checked = []
    for name, v in gauges.items():
        s = _gauge_series(v)
        full = fed(*zip(*s)).fit()
        if full is None or (v["stop_t"] - s[0][0]) / full.period < 2.5:
            continue
        m = SweepModel()
        fit = None
        for i, (t, u) in enumerate(s):
            m.add(t, u)
            fit = m.fit()
            if fit is not None:
                break
        assert fit is not None, f"gauge {name}: never fitted"
        assert s[i][0] - s[0][0] <= 2.0 * fit.period      # fitted shortly after 1.5 periods
        rest = np.array(s[i + 1:])
        err = np.abs(fit.u_at(rest[:, 0]) - rest[:, 1]) / (fit.hi - fit.lo)
        assert np.median(err) <= 0.005, f"gauge {name}: median {np.median(err):.4f}"
        assert np.percentile(err, 95) <= 0.010, f"gauge {name}: p95 {np.percentile(err, 95):.4f}"
        assert fit.rms <= 0.006 * (fit.hi - fit.lo)
        checked.append(name)
    assert {"1", "3", "7", "8"} <= set(checked)


# --- AC3: fit conditions ----------------------------------------------------------------------

def test_fit_recovers_parameters():
    t, u = sweep(1.5, phase=0.13)
    fit = fed(t, u).fit()
    assert fit is not None
    assert fit.lo == pytest.approx(0.15, abs=2e-3) and fit.hi == pytest.approx(0.85, abs=2e-3)
    assert fit.period == pytest.approx(0.8, abs=2e-3)
    assert fit.rms < 1e-3
    tt = np.linspace(2.0, 3.0, 50)
    assert np.allclose(fit.u_at(tt), tri_u(tt, phase=0.13), atol=3e-3)


def test_fit_none_with_too_few_samples():
    assert SweepModel().fit() is None
    t, u = sweep(0.1)
    assert fed(t, u).fit() is None


def test_fit_none_before_both_ends_seen():
    t = np.arange(0.0, 3.0, FP)            # one long ramp: 3 s observed, never turns
    assert fed(t, 0.2 + 0.2 * t).fit() is None
    t, u = sweep(0.4)                       # rising to the top only
    assert fed(t, u).fit() is None
    t, u = sweep(0.6)                       # up, then down: no low turn yet
    assert fed(t, u).fit() is None


def test_fit_none_before_one_and_a_half_periods():
    t, u = sweep(1.1)                       # 1.375 periods, both turns seen
    m = fed(t, u)
    assert m.fit() is None
    for a in np.arange(1.1, 1.3, FP):       # 1.5 periods = 1.2 s
        m.add(a, tri_u(a))
    assert m.fit() is not None


def test_fit_none_when_noisy():
    rng = np.random.default_rng(1)
    t, u = sweep(3.0)
    assert fed(t, u + rng.normal(0, 0.02 * 0.7, u.size)).fit() is None       # 2 % of travel
    assert fed(t, u + rng.normal(0, 0.002 * 0.7, u.size)).fit() is not None  # 0.2 % of travel


def test_fit_trims_startup_transient():
    t, u = sweep(2.5, phase=0.3)
    u = u.copy()
    u[:10] += np.linspace(0.08, 0.0, 10)    # zoom-in / settling wobble
    fit = fed(t, u).fit()
    assert fit is not None
    tt = np.linspace(2.5, 3.5, 40)
    assert np.abs(fit.u_at(tt) - tri_u(tt, phase=0.3)).max() < 0.01


def test_times_at():
    fit = Fit(0.2, 0.8, 1.0, 0.0, 0.0)
    ts = fit.times_at(0.5, 0.0, 2.0)
    assert np.allclose(ts, [0.25, 0.75, 1.25, 1.75])
    assert np.allclose(fit.u_at(ts), 0.5)
    assert fit.times_at(0.9, 0.0, 2.0).size == 0
    assert np.allclose(fit.times_at(0.5, 0.3, 1.3), [0.75, 1.25])


# --- frame clock ------------------------------------------------------------------------------

def test_frame_clock_with_skipped_frames_and_jitter():
    rng = np.random.default_rng(2)
    k = np.array(sorted(set(range(0, 120)) - set(rng.choice(np.arange(1, 119), 30, replace=False))))
    ts = 5.0123 + k / 60.0 + rng.normal(0, 0.0005, k.size)
    period, phase = frame_clock(ts)
    assert period == pytest.approx(1 / 60, rel=2e-3)
    off = (phase - 5.0123) % period
    assert min(off, period - off) < 0.001


def test_frame_clock_exact_grid():
    period, phase = frame_clock(3.2 + np.arange(40) * 0.02)       # a 50 Hz game
    assert period == pytest.approx(0.02, rel=1e-6)
    assert phase == pytest.approx(3.2 % 0.02, abs=1e-6) or phase == pytest.approx(0.02, abs=1e-6)


def test_frame_clock_needs_data():
    assert frame_clock([]) is None
    assert frame_clock([0.0, 0.0167, 0.0333]) is None


# --- lead_min ---------------------------------------------------------------------------------

def test_lead_min_arithmetic():
    assert SAFETY == 0.10
    assert lead_min(0.25, 0.06) == pytest.approx(0.41)
    assert lead_min(0.6, 0.2) == pytest.approx(0.9)
    assert lead_min(0.6, 0.2, 0.08) == pytest.approx(0.98)
    assert lead_min(0.6, 0.2, 0.08, safety=0.0) == pytest.approx(0.88)
    assert lead_min(0.25, 0.06, start_delay=0.08, safety=0.2) == pytest.approx(0.59)


def test_plan_release_requires_lead_min():
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    with pytest.raises(TypeError):
        plan_release(fit, (FP, 0.0), (0.40, 0.43), 0.0, 0.06)


# --- plan_release -----------------------------------------------------------------------------

YELLOW = (0.40, 0.43)
CENTER = 0.5 * sum(YELLOW)


def center_fit(period):
    """Fit and a frame clock with a game frame exactly on a rising crossing of the yellow centre."""
    fit = Fit(0.15, 0.85, period, 0.0, 0.0)
    t_c = float(fit.times_at(CENTER, 0.0, period)[0])
    return fit, (FP, t_c % FP), t_c


def brute(fit, fc, yellow, t_min, t_max):
    k = np.arange(np.ceil((t_min - fc[1]) / fc[0] - 1e-9), np.floor((t_max - fc[1]) / fc[0]) + 1)
    ft = fc[1] + k * fc[0]
    u = fit.u_at(ft)
    marg = np.minimum(u - yellow[0], yellow[1] - u)
    return ft, u, marg


def test_plan_picks_largest_margin_and_release_t():
    fit, fc, t_c = center_fit(0.8)
    now = t_c - 0.5
    plan = plan_release(fit, fc, YELLOW, now, 0.06, lead_min=0.3)
    assert isinstance(plan, Plan)
    assert plan.frame_t == pytest.approx(t_c, abs=1e-9)
    assert plan.margin == pytest.approx(0.015, abs=1e-9)
    assert plan.predicted_u == pytest.approx(CENTER, abs=1e-9)
    assert plan.release_t == pytest.approx(plan.frame_t - 0.06)


@pytest.mark.parametrize("k", range(24))
def test_plan_matches_brute_force_and_margin_rule(k):
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    fc = (FP, k * FP / 24)
    yellow = (0.40, 0.43)
    now, lead = 10.0, 0.41
    plan = plan_release(fit, fc, yellow, now, 0.06, lead_min=lead)
    ft, u, marg = brute(fit, fc, yellow, now + lead, now + lead + 6 * fit.period)
    best = marg.max()
    assert plan is not None
    assert plan.margin == pytest.approx(best)
    assert plan.frame_t >= now + lead - 1e-9
    assert plan.release_t == pytest.approx(plan.frame_t - 0.06)
    assert marg[np.argmin(np.abs(ft - plan.frame_t))] == pytest.approx(best)


def test_plan_releases_when_yellow_is_narrower_than_one_frame_step():
    # AI-NOTE: yellow 0.001 u wide, the sweep moves 0.029 u per frame: usually no frame reaches a 15 %
    # margin, for some frame phases none is in yellow at all. The planner must still answer: the in-yellow
    # frame with the LARGEST margin (earliest of equals, not a first frame grazing an edge), else the
    # frame nearest the yellow centre.
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    yellow, now, lead = (0.4000, 0.4010), 0.0, 0.41
    seen = set()
    for k in range(50):
        fc = (FP, k * FP / 50)
        plan = plan_release(fit, fc, yellow, now, 0.06, lead_min=lead)
        ft, u, marg = brute(fit, fc, yellow, now + lead, now + lead + 6 * fit.period)
        assert plan is not None
        assert plan.frame_t >= now + lead - 1e-9
        assert plan.release_t == pytest.approx(plan.frame_t - 0.06)
        if marg.max() > 0:
            seen.add("in")
            assert plan.margin == pytest.approx(marg.max())
            assert plan.frame_t == pytest.approx(ft[np.argmax(marg >= marg.max() - 1e-12)])
        else:
            seen.add("out")
            assert abs(plan.predicted_u - 0.4005) == pytest.approx(np.abs(u - 0.4005).min())
    assert seen == {"in", "out"}


def test_plan_none_without_fit_or_clock():
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    assert plan_release(None, (FP, 0.0), YELLOW, 0.0, 0.06, lead_min=0.4) is None
    assert plan_release(fit, None, YELLOW, 0.0, 0.06, lead_min=0.4) is None


def test_plan_still_answers_when_yellow_is_off_the_sweep():
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    plan = plan_release(fit, (FP, 0.0), (0.9, 0.93), 0.0, 0.06, lead_min=0.4)
    assert plan is not None and plan.margin < 0


@pytest.mark.parametrize("name,press,latency,start", PROFILES)
def test_plan_never_starts_in_the_past(name, press, latency, start):
    lm = lead_min(press, latency, start)
    for period in (0.4, 0.55, 0.8, 1.4):
        fit = Fit(0.15, 0.85, period, 0.0, 0.0)
        for ph in (0.0, 0.004, 0.011):
            for now in np.arange(20.0, 20.0 + period, period / 17):
                plan = plan_release(fit, (FP, ph), YELLOW, now, latency, lead_min=lm)
                if plan is None:
                    continue
                assert plan.frame_t - now >= lm - 1e-9
                assert plan.release_t - press - start >= now + SAFETY - 1e-9
                assert plan.release_t == pytest.approx(plan.frame_t - latency)


@pytest.mark.parametrize("name,press,latency,start", PROFILES)
def test_plan_skips_best_frame_inside_lead_min(name, press, latency, start):
    lm = lead_min(press, latency, start)
    fit, fc, t_c = center_fit(0.4)                      # fast sweep: 0.38-0.64 s end to end
    now = t_c - 0.3                                     # the exact-centre frame is 0.3 s away
    unconstrained = plan_release(fit, fc, YELLOW, now, latency, lead_min=0.0)
    assert unconstrained.frame_t == pytest.approx(t_c, abs=1e-9)
    assert lm > 0.3                                     # ... which is inside every profile's lead
    plan = plan_release(fit, fc, YELLOW, now, latency, lead_min=lm)
    assert plan is not None
    assert plan.frame_t - now >= lm - 1e-9
    assert plan.frame_t > t_c + 0.1
    m = np.ceil((now + lm - t_c) / 0.4 - 1e-9)           # first exact-centre crossing that is late enough
    assert plan.frame_t == pytest.approx(t_c + 0.4 * m, abs=1e-6)
    assert plan.margin == pytest.approx(0.015, abs=1e-6)


# --- AC5: latency calibration -----------------------------------------------------------------

def test_latency_cal_limits_and_default():
    cal = LatencyCal()
    assert cal.estimate() == DEFAULT_LATENCY["gpg"]
    assert LatencyCal(default=DEFAULT_LATENCY["ld"]).estimate() == 0.2
    for bad in (-0.001, 0.501, 2.0, None):
        assert cal.add(bad) is False
    assert cal.samples == [] and cal.estimate() == 0.06
    assert cal.add(0.0) and cal.add(0.5)
    assert cal.samples == [0.0, 0.5]


def test_latency_cal_median_of_last_seven():
    cal = LatencyCal()
    for s in (0.40, 0.45, 0.30):                       # old samples fall out of the window
        cal.add(s)
    for s in (0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11):
        cal.add(s)
    assert cal.estimate() == pytest.approx(0.08)
    cal.add(0.9)                                        # ignored, window unchanged
    assert cal.estimate() == pytest.approx(0.08)
    cal.add(0.20)
    assert cal.estimate() == pytest.approx(0.09)       # window 0.06 .. 0.11, 0.20


def test_latency_sample_sign():
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    t_star = float(fit.times_at(0.40, 0.0, 0.8)[0])    # rising crossing of the stopped position
    assert latency_sample(fit, 0.40, t_star - 0.06) == pytest.approx(0.06, abs=1e-9)
    assert latency_sample(fit, 0.40, t_star - 0.10) == pytest.approx(0.10, abs=1e-9)
    # AI-NOTE: the first crossing after UP wins; the falling pass 0.514 s later is not looked at
    assert latency_sample(fit, 0.40, t_star - 0.30) == pytest.approx(0.014285714, abs=1e-6)
    assert latency_sample(fit, 0.40, t_star + 0.01) == pytest.approx(-0.01, abs=1e-9)
    assert latency_sample(fit, 0.95, 1.0) is None
    cal = LatencyCal()
    assert not cal.add(latency_sample(fit, 0.40, t_star + 0.01))


def test_error_ms_sign():
    fit = Fit(0.15, 0.85, 0.8, 0.0, 0.0)
    t_c = float(fit.times_at(CENTER, 0.0, 0.8)[0])
    assert error_ms(fit, YELLOW, t_c) == pytest.approx(0.0, abs=1e-6)
    assert error_ms(fit, YELLOW, t_c - 0.020) == pytest.approx(-20.0, abs=1e-6)     # early
    assert error_ms(fit, YELLOW, t_c + 0.015) == pytest.approx(15.0, abs=1e-6)      # late
    t_f = float(fit.times_at(CENTER, 0.4, 0.8)[0])                                  # falling pass
    assert error_ms(fit, YELLOW, t_f - 0.01) == pytest.approx(-10.0, abs=1e-6)
    assert error_ms(fit, YELLOW, t_f + 0.01) == pytest.approx(10.0, abs=1e-6)
