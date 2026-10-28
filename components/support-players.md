---
title: Support players (Perception, BasePlayer, CollectPlayer)
type: component
updated: 2026-10-29
sources: [rdf01-t10]
---
# Support players (Perception, BasePlayer, CollectPlayer)

`tools/support_players.py` is the shared per-tick skeleton for the support deck plus the collect-mode player. Play and trial players (and `play()`/`main()`) are not written yet; [support-bot-core](support-bot-core.md) `run_battle` will call them.

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

## Pitfalls
- Same rule as the core: tests must use fakes (FakeGrabber/injector/saver/perception, injected `clock` and `sleep`) and never import `gear_loop`, `run_all`, `supervisor` or `discord_bot`.
- Importing the module has no side effects; it only inserts `src` on `sys.path`.
- Tick order mirrors `tools/gear_bot.py` `play()`.

## Evidence
- commit `8482bf1` — adds tools/support_players.py (Perception wrappers, BasePlayer.tick order and cadence constants, CollectPlayer behaviour) and tests/test_support_collect_player.py (fake-based tests); cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t10/task.json` — task spec
