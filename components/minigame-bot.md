---
title: Minigame bot loop (군밀 대청소)
type: component
updated: 2026-11-02
sources: [rdf05-t5]
---
# Minigame bot loop (군밀 대청소)

`tools/minigame_bot.py` runs the gauge loop: finds a gauge, tracks the tip, plans with
[policy-minigame.md](policy-minigame.md), presses 멈춰 early and releases on time. Three modes: live
(`--execute` sends input, without it a dry run prints "would release"), and `--replay REC.mp4` offline. The user
starts each 대청소 round by hand; the bot runs until Ctrl+C. Not wired into run_all or the supervisor.

## Entry points
- `main(argv, *, seams=None, out=print)`; importing has no side effects. `seams` replace preflight, grabber,
  injector, clock and sleeper in tests.
- Flags: `--profile gpg|ld`, `--execute`, `--cancel-test` (execute only, checks `cancel()` once), `--probe-input`
  (LD: print the release method and exit), `--replay PATH`.
- Exit codes: 0 Ctrl+C or end of replay, 2 bad command line, 3 guard stop or failed start check, else crash.
- `GaugeLoop` states: WAIT (full grab ~50 ms) -> CONFIRM -> TRACK -> PLAN -> HOLD (execute) or WOULD (dry run,
  replay) -> RESULT -> WAIT. `VideoSource` feeds a video as frames (t = frame index / fps).

## Behaviour that is not obvious
- A new gauge is confirmed by two fresh reads that agree (`same_bar`) and the bar span having been still for
  0.3 s with a moving tip. `same_bar` compares bar span and yellow interval within 0.004 u and is deliberately
  looser than `perception.same_gauge`: on the recording the first blue/purple edge is misread for 2-4 frames when
  the triangle sits under it.
- Guards: start check via `preflight.check([profile], place=True)` (failure -> exit 3 with the reason); window
  moved -> stop; covered game -> no press (`COVERED_WARN` once per gauge) and no strip PNG; a press is never sent
  late (if the clock passed the first action, nothing is sent and the plan is dropped); 3 releases in a row where
  the tip kept moving for 1 s -> stop.
- Ctrl+C, guard stops and crashes call `injector.cancel()`, never a plain release (a release would click 멈춰).
- LD swipe fallback: `press()` only keeps the point, `release_swipe()` is the whole gesture; `--cancel-test` is
  skipped for it.
- `--cancel-test` cancels instead of releasing on the first hold and prints whether the tip kept moving.
- Replay judges the planned frame, not the user's stop: yellow if the tip sits in yellow at the planned frame
  while the video still follows the fitted sweep (3 % of travel), else "확인 불가". Gate measured on
  `gpg_20261102_003916.mp4` (latency 0, GPG lead 0.25): 8 gauges, 1 of 1 verifiable plans yellow, 4 unverifiable,
  3 without plan (gauge 1: yellow narrower than one frame step; 2 and 4: stop before 1.5 periods). Console texts
  are the constants at the top of the module (`REPLAY_END`, `RESULT`, ...).

## Files written (`data/minigame/`)
- `gauges.jsonl` — one JSON line per gauge: ts, profile, execute, n, bar, yellow, period_s, fit_rms,
  frame_period_s, planned_frame_t, press_sent_t, release_sent_t, latency_used, latency_sample, stop_u, zone,
  manual, error_ms, cancel_test.
- `latency_<profile>.json` — `{samples (last LATENCY_WINDOW), updated, method}`, written atomically (tmp +
  `os.replace`) only with `--execute`. On load a file whose `method` differs from the current input method
  (postmessage / sendevent / swipe) is ignored; the dry run accepts any.
- `strips/<stamp>_<profile>_g<n>.png` — crop of the bar and result text, exclusive-create with `_2`..`_99`
  suffixes (same rule as save_frame).

## Not yet proven
Live runs: the latency defaults, `PREP_S`/`REFIT_S` timings and the real input path are unverified (H5).

## Evidence
- commit 04439fd (task/rdf05-t5, not yet merged, files not yet in the main checkout) adds:
  - tools/minigame_bot.py — all of the above; module docstring holds the replay gate numbers, `_hold`, `_result`, `_record`, `load_latency`/`save_latency`, `_main_live`.
  - tests/test_minigame_bot.py — `test_replay_gate_on_recording` and the loop, guard, record and latency-file tests.
