---
title: Support players (Perception, BasePlayer, CollectPlayer, PlayPlayer)
type: component
updated: 2026-10-30
sources: [rdf01-t10, rdf01-t11, rdf01-t16, rdf01-i1, rdf02-t5, rdf02-t6, rdf02-i1, rdf02-m1, rdT03]
---
# Support players (Perception, BasePlayer, CollectPlayer, PlayPlayer)

`tools/support_players.py` is the shared per-tick skeleton for the support deck plus the collect-mode and board-play players. All three players are written; `support_bot.play()` ([support-bot-core](support-bot-core.md)) builds them and `run_battle` calls `play()`.

## Perception
`Perception` is a thin class of one-line wrappers over `board` (`is_battle`, `is_game_over`, `board_glare`), `gear` (`ui_state`, `power_buttons`, `tactic_sp1000_card`, `dice_info_panel`, `banner_present/text`, `effect_kind`, `buffed_cells`, `cell_crops`) and `support` (`read_board_support`, `power_cards`, `card_level`, `read_cells_support`) and `score.read_score`, plus `frames_equal(a, b)` (same shape and `np.array_equal`). Players take it as `perc=` so tests script what a tick sees without images.

## BasePlayer.tick priority (first match wins)
1. `g.window_moved()` true -> return `"moved"` (an `OSError` from it skips the tick); 2. game over -> `"game_over"`; 2b. dice info panel (below); 3. tactic SP1000 card -> tap it, sleep 1.2; 4. `ui["hunt_popup"]` -> tap `hunt_popup_ok`; 5. `ui["power_panel"]` -> subclass `on_panel`; 6. `ui["hunt"]` and >= 3 s since last hunt tap -> tap `hunt`; 7. not battle -> nothing; 8. data cadence, then subclass `battle_tick`.
- **Dice info panel (rdT03):** checked right after game over, before the tactic check (the panel under a boss banner would fool the tactic OCR). `gear.dice_info_panel` = dark-pixel share in three bands (v 0.03-0.15 / 0.20-0.28 / 0.52-0.585) all above 0.40/0.60/0.70, never the banner band; it prints `dice info panel -> 소환 (close)`, taps `summon` (this tap only closes the panel, no summon, no SP) and returns with no board read, memory, burst or crop; a repeat tap only >= 1.0 s (`INFO_TAP_GAP`) later with the panel still up. Tests: tests/test_support_dice_info.py.
- `battle_start` is set on the first battle frame; `t(now)` is seconds since then (0.0 before).
- Data cadence in battle time: cells every 15 s (`CELLS_EVERY`, with `buffed` and `glare` kwargs), full frame every 30 s (`FRAME_EVERY`) to `data/support_frames/<game_id>/<t>.png`. Both go through the `Saver`, which re-checks `unobscured()` per call; the player never writes files itself.
- `run(minutes)` sleeps `tick` (0.6 s) then ticks; returns `"game_over"`, `"moved"` or `"timeout"`. `close_panel()` taps `power_close` up to 4 times until `ui_state` shows the panel gone.
- `stats` starts `{"merges":0,"fails":0,"support":0,"complete":False}`; `game_id` defaults to `support_bot.new_game_id()` (imported lazily).

## CollectPlayer
Summons (tap `summon`, >= 1 s apart); at battle time >= 120 s (`PANEL_AT`) taps `power_open` once. On the first panel seen after that it saves one `panel_<t>.png` frame, then only closes the panel. It never touches the board, hpsp or transcend and never taps a power card, so it cannot buy a power-up.

## PlayPlayer (board play)
`PlayPlayer(trial=False, deck=None)` extends BasePlayer. `trial=True` reads pips with `read_board_support(pip_source="gear")`, otherwise `"auto"`; both use the same tick rules. `battle_tick` order: banner OCR, raw board read, `CellMemory.update` (effective board `b`), burst if due, merge verification, guards, `plan_support`, action.
- **Effective board (rdf02-t6):** `self.memory = CellMemory(READ_CONF_MIN)` turns the raw read into `b`; `plan_support`, the stability check (`sig`) and the R13 line use `b`. `fmt_board` marks cells with `src` memory/burst with a trailing `*`. Memory events print: `cell N unreadable -> keep <tok> (last confident read)`, `cell N unreadable -> occupied, unknown` (once per cell until it leaves `unknown`), `board changed without our action at <cells> -> forget remembered <cells|none>` (bumps `stats["forgets"]`). A swipe calls `memory.own_action([from, to])`; a supporter swipe calls `memory.supported(from)`.
- **Bursts:** each tick `burster.due(now, unread, memory)`; `_burst` runs it, books it with `burster.done`, applies accepted results through `memory.apply_burst` into the effective board, prints `burst cells 3,7 -> 3=Re3 7=? (4 of 6 grabs)` (the tick frame counts as a grab in the log; the record's `grabs` is grabs taken), saves via `maybe_save`. After each `apply_burst`, every `external` event (R7.4) sets the effective cells in its `forgot` list to junk/pip 0/src `unknown` for this tick, including cells resolved earlier in the same burst, so the board differs from the previous tick and cannot count as stable with a forgotten die on it. Stats: `bursts`, `burst_hits` (accepted cells), `mem_ticks` (ticks with any memory cell), `forgets`.
- **Guards (R2):** no board action unless two consecutive effective boards are identical (skipped when the board is empty); more than 3 RAW unreadable cells (`len(unread) > MAX_JUNK`, not effective junk) -> no action; a merge or supporter touching a `buffed_cells` cell needs 4 identical reads of that cell (`BUFF_STEADY`). While a merge is being verified, `merge`/`support` are not issued (summon still is).
- **Merge verification (R7.1):** `_pending = [from, to, {cell: (type, pip)} at the swipe, undecided ticks]`; each tick `merge_verdict` runs on the RAW reads against those values. `effect` -> `memory.merged(from, to)`, and a still-`memory` effective cell is overwritten with junk/unknown for that tick. `none` -> prints `merge a->b had no effect -> banned until those dice change`, bans the pair, saves failure crops (`collect.save_fail`, only if `unobscured()`), bumps `stats["fails"]`. `undecided` (cells unreadable) is retried up to `VERIFY_TICKS` 3 ticks, then counts as `effect` (no ban, no fail count). The ban is keyed on die types only (a flickering pip read must not clear it) and expires after 90 s.
- **Actions:** summon taps >= 0.5 s apart; supporter swipe from the cell to `gear.UI["support"]` only when >= 130 s since the last; merge/supporter print the R13 board line and bump `stats["merges"]`/`["support"]`. `stats["complete"]` turns True once `evaluate_support` reports complete. hpsp and transcend are never tapped.
- **Banners:** OCR at most every 3 s. `destroy3_clone_max` sets `clone_until = now+45` (passed to `plan_support` as `clone_alert`); `sp_double_later` sets `hold_power_until = now+65` (gates the power bar); `summon_bonus_when_short` only prints.
- **Power bar (R13 step 10):** `_power_due` = >= 20 s (`POWER_EVERY`) since the last power visit/tap and `now > hold_power_until`. When the board is complete it prints `power-up (complete)`; when `plan_support` says `wait` it prints `idle (<why>) -> power-up`; either taps `power_open`. Both are only reached after the R2 guards.
- **Power visit (R20), `on_panel` -> `power_visit(f)`:** saves the panel frame (`panel_<t:.1f>.png`) before any buy tap; `power_cards` finds the card centres (none -> `power panel: cards not found -- closed`). Levels are read twice via `card_level`, with a fresh `g.grab()` after `sleep(0.3)`; a card whose two reads differ or are None counts as unread (PowerTracker counts it, line ends `, count)`). Cards `power_cards` did not find are passed as `found` to `start_visit`: they show `-` in the line and do not turn `src` into `count`. `plan_visit(levels, available, cfg, 6)` gives the buy order (empty -> `power panel: nothing to buy -- closed`); buy taps are 0.15 s apart, then `PowerTracker.line` is printed and `close_panel()`.
- **Score/milestones (R14):** every battle tick feeds `read_score` to `ScoreTracker`; a confirmed value goes to `MilestoneTracker.on_score`. On a stable board `on_board({res7, align7, bubbles})` is fed too. Each event prints its log line and saves a screenshot to `data/support_runs/<game_id>/<id>_<score|na>.png` or `cross_<S>_<score>.png`; a covered window (Saver returns None) stores shot null via `set_shot`.
- `last_frame` (last battle frame) is kept for `play()`'s `end.png`.

## Burster (burst mechanics, called by PlayPlayer since rdf02-t6)
`Burster(player)` holds the burst state and only grabs and reads; it never touches the injector. `PlayPlayer._burst` drives it (see above); CollectPlayer does not use it. Constants: `BURST_N` 6 (tick frame + 5 grabs), `BURST_DT` 0.08 s, `BURST_GAP` 3 s between bursts, `BURST_REFRESH` 15 s, `BURST_FAILS` 3, `BURST_SAVE_GAP` 10 s, `BURST_SAVE_MAX` 60.
- `due(now, unreadable_cells, memory)` -> ascending cells to burst. Empty if < `BURST_GAP` since any burst or if the unreadable count is not 1..`MAX_JUNK`. A cell is due when `memory.state(c)` is `unknown` (unless it failed `BURST_FAILS` bursts in a row and its last burst is < `BURST_REFRESH` ago) or `remembered` with the last burst >= `BURST_REFRESH` ago.
- `run(f, cells, pip_source)` -> `(kept, reads, grabs)`. The tick frame `f` is kept as is; each of the 5 grabs is dropped if it is not battle or equals the previous kept frame (the grabber repeats the last frame when dxcam sees no change, and a repeat must not count as a second read). Every kept frame is read with `read_cells_support`.
- `done(now, cells, results, reads, conf_min)` books the burst: `fails[c]` resets to 0 if the cell has an accepted result or any read that is not `_unreadable` (imported from support_memory: non-junk, finite conf, `conf >= conf_min`), else it grows by 1. A NaN conf therefore keeps the backoff counting.
- `record(...)` builds the `bursts.jsonl` line (game, t, cells, grabs, kept, reads as `[type, pip, conf]`, result, memory, buffed, glare).
- `maybe_save(game_id, t, cells, kept, record)` calls `Saver.burst` at most every `BURST_SAVE_GAP` s and `BURST_SAVE_MAX` times; a covered window (`None`) does not use up the quota or restart the gap. File layout: [capture-live](capture-live.md). Memory side: [support-memory](support-memory.md).

## Covered window during a burst
`tests/test_support_play_m1.py` pins this with a Saver whose `unobscured()` is False: the burst still runs, its accepted value enters the effective board and the plan of that tick (src `burst`), no burst file or `bursts.jsonl` line is written, and the burst does not count toward `BURST_SAVE_MAX`. This worked without a code change.

## Pitfalls
- Levels are read only at visit start, never after a buy tap: the number updates a beat after the tap (HP-reader lesson), so a post-tap read would be stale.
- Same rule as the core: tests must use fakes (FakeGrabber/injector/saver/perception, injected `clock` and `sleep`) and never import `gear_loop`, `run_all`, `supervisor` or `discord_bot`.
- Importing the module has no side effects; it only inserts `src` on `sys.path`.
- Tick order mirrors `tools/gear_bot.py` `play()`.

## Evidence
- commit `5115ba1` — support_players.py calls `start_visit(read, set(found))` and prints the line from `levels` directly; test `test_power_visit_missing_card_does_not_make_src_count` in test_support_play_power; cited by commit because the files are not yet in the main checkout
- commit `8482bf1` — adds tools/support_players.py (Perception wrappers, BasePlayer.tick order and cadence constants, CollectPlayer behaviour) and tests/test_support_collect_player.py (fake-based tests); cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t10/task.json` — task spec
- commit `ce6f41a` — adds PlayPlayer (guards, merge ban, banner timers, trial pip_source, provisional panel_hook, since replaced) to tools/support_players.py and tests/test_support_play_player.py; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t11/task.json` — task spec
- commit `db27b4f` — adds power bar, power_visit, score/milestone wiring, last_frame to tools/support_players.py and tests/test_support_play_power.py (fakes with scripted scores and panel levels); cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t16/task.json` — task spec AC1–AC7
- `tools/support_players.py` — `Burster`, `BURST_*` constants, `Perception.read_cells_support` / `frames_equal` (rdf02-t5); commit `558b79e` adds tests/test_support_burst.py (fake-based tests of due/run/done/maybe_save), cited by commit because the file is not yet in the main checkout
- `C:/dev/_hub/tasks/rdf02-t5/task.json` — task spec
- `tools/support_players.py` — `PlayPlayer.__init__` (memory, burster, stats), `_log_events`, `_burst`, `_verify_merge`, `VERIFY_TICKS`, `fmt_board` `*` marker, `battle_tick` order (rdf02-t6); commit `78aa900` adds tests/test_support_play_memory.py (fake-based) and adjusts tests/test_support_play_player.py
- `C:/dev/_hub/tasks/rdf02-t6/task.json` — task spec
- commit `be50e5f` — `PlayPlayer._burst` in tools/support_players.py blanks `ev["forgot"]` cells after `apply_burst`; test `test_burst_external_event_forgets_cell_resolved_earlier_in_burst` in tests/test_support_play_memory.py; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf02-i1/task.json` — integration finding and AC1
- commit `f4a6837` (branch task/rdf02-m1) — `Burster.done` uses `_unreadable` in tools/support_players.py; test `test_burster_done_non_finite_conf_does_not_reset_fail_counter` in tests/test_support_m1_inputs.py; commit `2e74942` adds `test_covered_window_burst_runs_but_saves_and_counts_nothing` in tests/test_support_play_m1.py
- `tools/support_players.py`, `src/rdom/perception/gear.py` — `dice_info_panel`/`dice_info_scores`, `INFO_TAP_GAP`, `_info_last`, tick branch before the tactic check (rdT03; measured scores in the `dice_info_panel` docstring); tests/test_support_dice_info.py with fixtures tests/fixtures/dice_info_banner.png, dice_info_plain.png and neg_*.png
- `C:/dev/_hub/tasks/rdT03/task.json` — task spec (H2 game 1 stall, 2026-10-30)
