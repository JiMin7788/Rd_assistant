---
title: Minigame gauge simulation and report (군밀 대청소)
type: component
updated: 2026-11-02
sources: [rdf05-t6]
---
# Minigame gauge simulation and report (군밀 대청소)

An offline regression check of OUR OWN game model: the real `GaugeLoop`, `read_gauge`, `lead_min` and `plan_release`
run against a simulated game. It says nothing about the real game (spec R11); real behaviour is compared in H5 step 2.
`tools/minigame_report.py` summarises the live `gauges.jsonl` records.

## Sim (`src/rdom/sim/gauge_sim.py`, `tools/minigame_sim.py`)
- Simulated: `VirtualClock` (+ sleeper), `SimGame` (game frame clock at a random phase, triangle-wave tip, a new
  gauge ~1 s after each result), `SimSource` (synthetic full and band frames the real recognizer reads),
  `SimInjector` (press/release/cancel/release_swipe; logs planned, scheduled and sent time of every action).
- UP arrival = sent + latency + U(-jitter, +jitter); the game stops the tip at the first game frame >= arrival; the
  zone comes from the true tip, never from the bot's reading. Swipe adds a spawn delay `start_delay` ± `start_jitter`.
- `python tools/minigame_sim.py --case gpg|ld60|ld30|ld60swipe --gauges N --seed S` prints
  `sim <case>: 노랑 <y>/<n> (<pct>%)` and the latency estimate. Every case starts from a fresh `LatencyCal` with a
  wrong guess (gpg 0.060, LD 0.200) and must converge on its own.
- Gates in `tests/test_minigame_sim.py`: gpg, seeded, 104 gauges, >= 98 yellow among gauges 5..104; for all four cases
  no DOWN/spawn is scheduled before its plan was made and every sent DOWN/spawn is <= 2 ms after its scheduled time.
  LD hit rates are recorded in the module docstring, not gated (seed 1, 40 gauges: ld60 22, ld30 26, ld60swipe 13;
  gpg 103/104). Cause: the assumed LD jitter (±25 ms, swipe start ±30 ms) exceeds a 16.7 ms game frame.

## Pitfall found by the sim: AIM_FRAC
A latency sample is "stop frame - UP sent" = true latency + the gap between UP arrival and that frame (0..1 frame), so
the median settled where the UP arrives just before a frame and any jitter tipped the stop onto the next frame (GPG
91/100 yellow). `tools/minigame_bot.py` now plans with `estimate() + AIM_FRAC * frame_period` (`AIM_FRAC = 0.25`),
stores the aim as `_Gauge.aim_used` and subtracts it from the sample in `_result`; the "놓음 (지연 N ms)" text shows
only the calibrated part. Replay uses no aim. `lead_min` therefore includes the aim.

## Report (`tools/minigame_report.py [--profile P] [--file F]`)
Read-only, default `data/minigame/gauges.jsonl`. Counts only records with execute true, manual false and not
cancel_test; prints the profile line (노랑/보라/파랑/바깥), the latency median and range, and early/late misses with
mean error, or `<profile>: 기록 없음`. Exact texts are in the spec R11 and the tests.

## Evidence
- commit e7c4619 (task/rdf05-t6, not yet merged, files not yet in the main checkout) adds:
  - src/rdom/sim/gauge_sim.py — classes above; module docstring holds the hit rates and the AIM_FRAC finding.
  - tools/minigame_sim.py — the `--case` CLI and output line.
  - tools/minigame_report.py — the report.
  - tests/test_minigame_sim.py — the gpg 98/100 gate and the timing gates for four cases.
  - tools/minigame_bot.py — `AIM_FRAC`, `aim_used`, aim taken off the sample in `_result`.
