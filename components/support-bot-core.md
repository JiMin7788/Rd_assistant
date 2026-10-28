---
title: Support bot core (routing, saver, mode, round record)
type: component
updated: 2026-10-29
sources: [rdf01-t9, rdf01-t16]
---
# Support bot core (routing, saver, mode, round record)

`tools/support_bot.py` holds the small, unit-testable blocks of the support player: deck routing, the R6-guarded saver, the R4 mode choice, the R14 round record, `run_battle`, `play()` and the CLI `main()`. The per-tick players live in [support-players](support-players.md); `gear_loop` is not yet changed to call `run_battle`.

## Contents
- `route_deck(g, detect, force, sleep)` -> `"support"` or `"gear"`. `force()` == `"support"` returns at once, printing `deck route: support (forced by deck.toml)`, without grabbing. Otherwise up to 20 frames, 0.5 s apart (`sleep` between frames only), and 2 consecutive `detect(frame)` hits give `deck route: support (deck bar)`; a miss resets the run, so hits on frames 3 and 5 only still end in `deck route: gear`.
- `Saver(g)`: `.cells(frame, game_id, t, **kw)` and `.frame(frame, path)` call `collect.save_support_cells` / `collect.save_frame` with `unobscured=g.unobscured()` evaluated on every call (never cached), so a window covered mid-game writes nothing.
- `choose_mode(gates)` -> `(mode, log line)`: type gate false -> `collect` (even if pip is true); type true + pip false -> `trial`; both -> `play`. Log lines are exact, e.g. `support deck: trial mode (type gate PASS, pip gate FAIL)`.
- `new_game_id(now)` -> `sup%Y%m%d_%H%M%S`.
- `build_record(...)` -> dict with exactly the R14 keys `game_id, wall_start, wall_end, result, mode, gates, max_score, scores_confirmed, milestones, crossings, power, stats`. The score/milestone/crossing parts come from `MilestoneTracker.record()` ([milestones](policy-milestones.md)), `power` from `PowerTracker.record()` or `None`; datetimes become ISO strings.
- `append_round(path, record)`: creates the parent dir, appends one UTF-8 JSON line (`ensure_ascii=False`); this is the file `tools/support_judge.py` reads.
- `run_battle(g, inj, minutes, route, gear_play, support_play)` -> `(result, player)`; the caller reads `player.stats`. If the gear player returns `"wrong_deck"`, it prints `deck route: support (gear bot hand-over)` and runs the support player in the same call. `minutes` is passed to the player as a keyword.
- `play(g, inj, minutes=40, tick=0.6, mode=None)`: `mode=None` -> `choose_mode(support.gate_state())`, else prints `support deck: <mode> mode (forced)`. Runs `CollectPlayer` for collect, else `PlayPlayer(trial=mode=="trial")`. After `run()` it saves `data/support_runs/<game_id>/end.png` through the Saver (player's `last_frame`, else a fresh grab), appends `build_record(...)` to `ROUNDS_FILE` (`data/support_rounds.jsonl`; power from `PowerTracker.record()`, `None` for collect) and sets `play.stats` (merges, fails, support, complete). Returns the player result.
- `main()`: argparse `--execute` (default off = dry run, `Injector(execute=a.execute)`), `--mode auto|collect|play`, `--minutes 40`, `--tick 0.6`. `auto` passes `mode=None`; the CLI cannot force `trial` (only auto picks it).

## Invariants and pitfalls
- No module-level side effects: only imports and constants (no grabber, injector, loop or file I/O).
- `gear_play` default imports `gear_bot` lazily inside the function. `support_play` default is looked up at call time with `getattr(sys.modules[__name__], "play")`, so tests can run with an explicit `support_play`; `play()` now exists as the default.
- Tests must never import `tools.gear_loop`, `run_all`, `supervisor` or `discord_bot` (they start the real bot); `tests/test_support_bot_core.py` uses fakes (FakeGrabber, fake detect/force/play callables, fake sleep).
- Related: [support perception](perception-support.md) (`detect_support_deck`, `force_deck`, `gate_state`), [capture writers](capture-live.md).

## Evidence
- commit `db3fff3` — adds support_bot (route_deck, Saver, choose_mode, new_game_id, build_record, append_round, run_battle, exact log strings, ROUTE_* constants) and its test_support_bot_core tests with fakes; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t9/task.json` — spec AC1–AC8 (route frames, mode table, record keys, wrong_deck hand-over)
- commit `db27b4f` — adds play(), main(), ROUNDS_FILE to tools/support_bot.py; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t16/task.json` — spec AC5–AC6 (play record, dry-run CLI)
