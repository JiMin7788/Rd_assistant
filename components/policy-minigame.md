---
title: Minigame release planner (군밀 대청소)
type: component
updated: 2026-11-02
sources: [rdf05-t2]
---
# Minigame release planner (군밀 대청소)

`policy/minigame.py` fits the tip's triangle wave from timestamped reads, finds the game-frame clock, picks a
future frame whose predicted tip is well inside yellow and says when to send UP. Pure numpy, no I/O, not wired
into any loop yet. Tip reads come from [perception-minigame.md](perception-minigame.md).

## Entry points
- `SweepModel.add(t, u)` / `fit()` -> `Fit(lo, hi, period, phase, rms)` or `None`. `Fit.u_at(t)` and
  `Fit.times_at(u, t_from, t_to)` (sorted crossing times).
- `frame_clock(times_moved)` -> `(frame_period, frame_phase)` or `None` (< 4 times). Input: capture times at
  which the tip moved.
- `lead_min(press_lead, latency, start_delay=0.0, safety=SAFETY)` = plain sum; `SAFETY` = 0.10 s.
- `plan_release(fit, frame_clock, yellow, now, latency, *, lead_min, horizon_periods=6, min_margin_frac=0.15)`
  -> `Plan(frame_t, release_t, margin, predicted_u)` or `None`. `lead_min` is a required keyword so a caller
  must pass the profile's lead (GPG press 0.25 / latency 0.06; LD sendevent 0.6 / 0.2; LD swipe adds
  start_delay 0.08).
- `LatencyCal` (`add`, `estimate`), `latency_sample(fit, stop_u, release_sent_t)`, `error_ms(fit, yellow, stop_t)`.
- `DEFAULT_LATENCY = {"gpg": 0.060, "ld": 0.200}` are unverified guesses (spec R7) until a live calibration.

## Behaviour that is not obvious
- `fit()` answers only when a high and a low turning point were seen, >= 1.5 periods of *settled* data exist and
  rms <= 0.6 % of travel. It is a deterministic grid search (closed-form lo/span per trial period and phase, then
  nested refinement); no scipy.
- Start-up transient: the bar zooms in and the tip settles in the first 0.1-0.4 s of a gauge (up to 5 % of travel
  off). The fit drops samples up to the last bad residual in the first half; only a bad stretch in the first half
  counts, scattered bad samples stay and fail the rms gate. The gates count the remaining samples only.
- No easing: on all 8 recorded gauges the motion is linear to the bounces (rms 0.02-0.05 % of travel), so no
  end part is cut. The fitted turning values lie 0.1-2.1 % beyond the highest sample (the peak falls between frames).
- `plan_release` never returns a frame earlier than `now + lead_min`; a better frame that is too near is skipped
  for a later crossing. Among equal margins the earliest wins. `release_t = frame_t - latency`.
- `None` when the best margin is below 15 % of the yellow width (this also covers "no frame in yellow").
- `LatencyCal.add` ignores samples outside [0, 0.5] s and `None`; `estimate()` = median of the last 7, else the
  default (the dataclass default is the GPG value; pass the LD one for LD). `latency_sample` can be negative by
  frame quantisation, which `add` then drops.
- `error_ms` is signed: negative = early, positive = late, 0 = yellow centre.

## Prediction gate (tests, recorded traces)
Fit at the first moment `fit()` is not None (about 1.5-1.7 periods), predict every later sample up to the user's
stop. Gauges with >= 2.5 periods (1, 3, 7, 8): median |error| 0.016-0.060 % of travel, p95 <= 0.134 %, max
0.163 %; far inside the 0.5 % / 1.0 % bars. Gauges 2 and 4 never reach 1.5 periods before the stop, so no fit.
Exact per-gauge table is in the module docstring.

## Not yet proven
Latency defaults and the real frame clock are unverified on live frames (H5 dry runs); persistence of the
latency and the loop that uses the planner belong to rdf05-t5.

## Evidence
- commit 90e6bfa (task/rdf05-t2, not yet merged, files not yet in the main checkout) adds:
  - src/rdom/policy/minigame.py — all entry points, constants, transient trimming, planner and the docstring with the easing and per-gauge error tables.
  - tests/test_minigame_policy.py — prediction gate on traces.json, fit-condition, frame_clock, plan_release (lead_min cases), LatencyCal, latency_sample and error_ms tests.
- tests/fixtures/rdf05/traces.json — recorded `[t, tip_u]` series, yellow interval and stop_frame used by the gate (from rdf05-t1).
