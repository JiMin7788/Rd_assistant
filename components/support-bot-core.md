---
title: Support bot core (routing, saver, mode, round record)
type: component
updated: 2026-10-30
sources: [rdf01-t9, rdf01-t16, rdf01-t13, rdf02-t5, rdf03-t2, rdf03-m1]
---
# Support bot core (routing, saver, mode, round record)

`tools/support_bot.py` holds the small, unit-testable blocks of the support player: deck routing, the R6-guarded saver, the R4 mode choice, the R14 round record, `run_battle`, `play()` and the CLI `main()`. The per-tick players live in [support-players](support-players.md); `tools/gear_loop.py` now calls `run_battle` (see Wiring).

## Contents
- `route_deck(g, detect, force, sleep)` -> `"support"` or `"gear"`. `force()` == `"support"` returns at once, printing `deck route: support (forced by deck.toml)`, without grabbing. Otherwise up to 20 frames, 0.5 s apart (`sleep` between frames only), and 2 consecutive `detect(frame)` hits give `deck route: support (deck bar)`; a miss resets the run, so hits on frames 3 and 5 only still end in `deck route: gear`.
- `Saver(g)`: `.cells(frame, game_id, t, **kw)`, `.frame(frame, path)` and `.burst(game_id, t, cells, grabs, record)` call `collect.save_support_cells` / `collect.save_frame` / `collect.save_burst` with `unobscured=g.unobscured()` evaluated on every call (never cached), so a window covered mid-game writes nothing.
- `choose_mode(gates)` -> `(mode, log line)`: type gate false -> `collect` (even if pip is true); type true + pip false -> `trial`; both -> `play`. Log lines are exact, e.g. `support deck: trial mode (type gate PASS, pip gate FAIL)`.
- `new_game_id(now)` -> `sup%Y%m%d_%H%M%S`.
- `build_record(...)` -> dict with exactly the R14 keys `game_id, wall_start, wall_end, result, mode, gates, max_score, scores_confirmed, milestones, crossings, power, stats`. The score/milestone/crossing parts come from `MilestoneTracker.record()` ([milestones](policy-milestones.md)), `power` from `PowerTracker.record()` or `None`; datetimes become ISO strings.
- `append_round(path, record)`: creates the parent dir, appends one UTF-8 JSON line (`ensure_ascii=False`); this is the file `tools/support_judge.py` reads.
- `run_battle(g, inj, minutes, route, gear_play, support_play)` -> `(result, player)`; the caller reads `player.stats`. If the gear player returns `"wrong_deck"`, it prints `deck route: support (gear bot hand-over)` and runs the support player in the same call. `minutes` is passed to the player as a keyword.
- `play(g, inj, minutes=40, tick=0.6, mode=None)`: `mode=None` -> `choose_mode(support.gate_state())`, else prints `support deck: <mode> mode (forced)`. Runs `CollectPlayer` for collect, else `PlayPlayer(trial=mode=="trial")`. After `run()` it saves `data/support_runs/<game_id>/end.png` through the Saver (player's `last_frame`, else a fresh grab), appends `build_record(...)` to `ROUNDS_FILE` (`data/support_rounds.jsonl`; power from `PowerTracker.record()`, `None` for collect) and sets `play.stats` (merges, fails, support, complete). Returns the player result.
- **Clear at 5000 (rdf03-t2):** user: "5000점이면 클리어로 끝남" -- a normal game ends as a clear at `CLEAR_SCORE = 5000`. When the player returns `game_over`, `play()` reads `Perception().read_score(player.last_frame)` (`final_score`, None without a last frame) and the result becomes `"clear"` if `max(milestones max_score, final_score or 0) >= 5000` (the tracker can miss the last digits, so the fresh read counts too). It prints `support result: <result> (max score <m>, last frame <f|->)`; `build_record(..., final_score=None)` adds a `final_score` key only when it was read. Non-game_over results are never turned into clear.
- `main()`: argparse `--execute` (default off = dry run, `Injector(execute=a.execute)`), `--mode auto|collect|play`, `--minutes 40`, `--tick 0.6`. `auto` passes `mode=None`; the CLI cannot force `trial` (only auto picks it).

## Wiring (rdf01-t13)
- `tools/gear_loop.py` calls `support.reload_if_changed()` after the gear reload (prints `support models reloaded: ...`), then `res, player = support_bot.run_battle(g, inj, minutes=40, gear_play=play)` and reads round stats from `getattr(player, "stats", {})`. Keyword args are required: `run_battle`'s third positional is `minutes`; passing `gear_play=play` keeps the `player is gear_play` hand-over check true.
- `tools/gear_bot.py` `play()` runs `support.detect_support_deck(frame)` on its first tick and then every 10 s, after the game-over check and before every other rule (so the support deck never gets the HP->SP rule). A hit prints `support deck seen in gear bot -- handing over` and returns `"wrong_deck"` without tapping.
- `tools/run_all.py` SHOW prefixes gained `milestone`, `deck route`, `support deck`, `frame not saved`, `power panel`, `power card`, so those lines reach the console.
- `config/deck.toml` has comments for `force = "support"` (H1 collection; empty it afterwards) and the `power_*` buying order. The human steps H1-H3 are in `CLAUDE_CODE_TODO.md` ("rdF01 서포팅덱").
- Tests: `tests/test_gear_bot_handover.py` loads `tools/gear_bot.py` by path with fakes (not `gear_loop`).

- **gear_loop end handling (rdf03-t2, rdf03-m1):** `tools/gear_loop.py` is importable: everything live (window placement, `LiveGrabber`/`Injector`, `send_status`, the loop, final prints) is in `main()`, run only under `if __name__ == "__main__":`. The end handling is the module-level `after_battle(res, g, inj, exit_fn=exit_to_lobby, battle_fn=is_battle, report=None)`: it prints `battle result: <res>`, runs `report()` (write_room closed + Discord round summary), returns True for `moved` (main breaks), and for `game_over`/`clear` sleeps 3 s, then checks a fresh `g.grab()` with `is_battle`; if a battle is on screen it prints `battle still on screen -- 로비로 가기 skipped` and does not call `exit_to_lobby` (which taps the lobby position blindly), else prints `로비로 가기: <result>`. `timeout` only logs. `tools/support_judge.py` `_exclusion` counts `clear` as eligible like `game_over`; any other result is `abnormal`.

## Invariants and pitfalls
- No module-level side effects: only imports and constants (no grabber, injector, loop or file I/O).
- `gear_play` default imports `gear_bot` lazily inside the function. `support_play` default is looked up at call time with `getattr(sys.modules[__name__], "play")`, so tests can run with an explicit `support_play`; `play()` now exists as the default.
- Tests must never import `run_all`, `supervisor` or `discord_bot` (they start the real bot). `tools.gear_loop` may be imported only through the `gl` fixture in `tests/test_gear_loop_result.py`, which booby-traps `place_game_window`, `LiveGrabber`, `Injector`, `send_status` and pops the module from `sys.modules` afterwards (other tests assert loop modules were never imported); `after_battle` is driven with fake `exit_fn`/`battle_fn`. `tests/test_support_bot_core.py` uses fakes (FakeGrabber, fake detect/force/play callables, fake sleep).
- Related: [support perception](perception-support.md) (`detect_support_deck`, `force_deck`, `gate_state`), [capture writers](capture-live.md).

## Evidence
- `tools/support_bot.py` — `Saver.burst` (rdf02-t5), forwards `unobscured=g.unobscured()` to `collect.save_burst`
- commit `db3fff3` — adds support_bot (route_deck, Saver, choose_mode, new_game_id, build_record, append_round, run_battle, exact log strings, ROUTE_* constants) and its test_support_bot_core tests with fakes; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t9/task.json` — spec AC1–AC8 (route frames, mode table, record keys, wrong_deck hand-over)
- commit `db27b4f` — adds play(), main(), ROUNDS_FILE to tools/support_bot.py; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t16/task.json` — spec AC5–AC6 (play record, dry-run CLI)
- `tools/gear_loop.py`, `tools/gear_bot.py`, `tools/run_all.py`, `config/deck.toml`, `CLAUDE_CODE_TODO.md` — the t13 wiring above (commit `e3cf60a`)
- commit `0ece85e` — `CLEAR_SCORE`, clear decision and `final_score` in `play`/`build_record` (tools/support_bot.py), the gear_loop battle guard, `_exclusion` change in tools/support_judge.py; cited by commit; spec `C:/dev/_hub/tasks/rdf03-t2/task.json`
- commit `e6bd06b` — rdf03-m1: gear_loop `main()` / `after_battle` split and tests/test_gear_loop_result.py (replaces the source-text guard test in tests/test_support_game_end.py); cited by commit; spec `C:/dev/_hub/tasks/rdf03-m1/task.json`
- commit `e3cf60a` adds tests/test_gear_bot_handover.py (cited by commit; not yet in the main checkout) — hand-over on first tick, detect cadence (first tick, then >=10 s)
