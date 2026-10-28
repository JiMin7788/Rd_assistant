---
title: Support players (Perception, BasePlayer, CollectPlayer, PlayPlayer)
type: component
updated: 2026-10-29
sources: [rdf01-t10, rdf01-t11]
---
# Support players (Perception, BasePlayer, CollectPlayer, PlayPlayer)

`tools/support_players.py` is the shared per-tick skeleton for the support deck plus the collect-mode and board-play players. `PlayPlayer` is written; power visits, score/milestones, `play()` and `main()` are not (t16); [support-bot-core](support-bot-core.md) `run_battle` will call them.

## Perception
`Perception` is a thin class of one-line wrappers over `board` (`is_battle`, `is_game_over`, `board_glare`), `gear` (`ui_state`, `power_buttons`, `tactic_sp1000_card`, `banner_present/text`, `effect_kind`, `buffed_cells`, `cell_crops`) and `support` (`read_board_support`, `power_cards`, `card_level`) and `score.read_score`. Players take it as `perc=` so tests script what a tick sees without images.

## BasePlayer.tick priority (first match wins)
1. `g.window_moved()` true -> return `"moved"` (an `OSError` from it skips the tick); 2. game over -> `"game_over"`; 3. tactic SP1000 card -> tap it, sleep 1.2; 4. `ui["hunt_popup"]` -> tap `hunt_popup_ok`; 5. `ui["power_panel"]` -> subclass `on_panel`; 6. `ui["hunt"]` and >= 3 s since last hunt tap -> tap `hunt`; 7. not battle -> nothing; 8. data cadence, then subclass `battle_tick`.
- `battle_start` is set on the first battle frame; `t(now)` is seconds since then (0.0 before).
- Data cadence in battle time: cells every 15 s (`CELLS_EVERY`, with `buffed` and `glare` kwargs), full frame every 30 s (`FRAME_EVERY`) to `data/support_frames/<game_id>/<t>.png`. Both go through the `Saver`, which re-checks `unobscured()` per call; the player never writes files itself.
- `run(minutes)` sleeps `tick` (0.6 s) then ticks; returns `"game_over"`, `"moved"` or `"timeout"`. `close_panel()` taps `power_close` up to 4 times until `ui_state` shows the panel gone.
- `stats` starts `{"merges":0,"fails":0,"support":0,"complete":False}`; `game_id` defaults to `support_bot.new_game_id()` (imported lazily).

## CollectPlayer
Summons (tap `summon`, >= 1 s apart); at battle time >= 120 s (`PANEL_AT`) taps `power_open` once. On the first panel seen after that it saves one `panel_<t>.png` frame, then only closes the panel. It never touches the board, hpsp or transcend and never taps a power card, so it cannot buy a power-up.

## PlayPlayer (board play)
`PlayPlayer(trial=False, deck=None)` extends BasePlayer. `trial=True` reads pips with `read_board_support(pip_source="gear")`, otherwise `"auto"`; both use the same tick rules. `battle_tick` order: banner OCR, board read, merge-effect check, guards, `plan_support`, action.
- **Guards (R2):** no board action unless two consecutive reads are identical (skipped when the board is empty); more than 3 junk (`unknown`) cells -> no action; a merge or supporter touching a `buffed_cells` cell needs 4 identical reads of that cell (`BUFF_STEADY`).
- **Merge ban:** the tick after a merge swipe, if both cells are unchanged it prints `merge a->b had no effect -> banned until those dice change`, bans the pair, saves failure crops (`collect.save_fail`, only if `unobscured()`) and bumps `stats["fails"]`. The ban is keyed on die types only (a flickering pip read must not clear it) and expires after 90 s.
- **Actions:** summon taps >= 0.5 s apart; supporter swipe from the cell to `gear.UI["support"]` only when >= 130 s since the last; merge/supporter print the R13 board line and bump `stats["merges"]`/`["support"]`. `stats["complete"]` turns True once `evaluate_support` reports complete. hpsp and transcend are never tapped.
- **Banners:** OCR at most every 3 s. `destroy3_clone_max` sets `clone_until = now+45` (passed to `plan_support` as `clone_alert`); `sp_double_later` sets `hold_power_until = now+65` (read by t16); `summon_bonus_when_short` only prints.
- **Panel:** `panel_hook`/`on_panel` is provisional: it only calls `close_panel()` (<= 4 `power_close` taps) and never buys. t16 replaces it.

## Pitfalls
- Same rule as the core: tests must use fakes (FakeGrabber/injector/saver/perception, injected `clock` and `sleep`) and never import `gear_loop`, `run_all`, `supervisor` or `discord_bot`.
- Importing the module has no side effects; it only inserts `src` on `sys.path`.
- Tick order mirrors `tools/gear_bot.py` `play()`.

## Evidence
- commit `8482bf1` — adds tools/support_players.py (Perception wrappers, BasePlayer.tick order and cadence constants, CollectPlayer behaviour) and tests/test_support_collect_player.py (fake-based tests); cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t10/task.json` — task spec
- commit `ce6f41a` — adds PlayPlayer (guards, merge ban, banner timers, trial pip_source, provisional panel_hook) to tools/support_players.py and tests/test_support_play_player.py; cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t11/task.json` — task spec
