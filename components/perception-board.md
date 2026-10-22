---
title: Board perception and cell tracker (Predator deck)
type: component
updated: 2026-10-23
sources: [seed]
---
# Board perception and cell tracker (Predator deck)

`perception/board.py` reads the own 5×3 field (15 cells → {type, pip, conf}) and screen states;
`perception/tracker.py` turns per-frame reads into per-cell beliefs so effect frames cause no actions.

## board.py
- Grid: column centres u 0.284/0.390/0.499/0.610/0.717, row centres v 0.551/0.621/0.690; cell =
  row*5+col+1. Opponent (top) board is not parsed for play.
- `classify_type` returns `predict_proba`-based confidence; unsure → `LOW_CONF` 0.45
  (`CONF_MIN` 0.60, `MARGIN_MIN` 0.25). Deck types: Predator/Light/Resonance/Bubble/Switch + empty/Bomb.
- Empty cell = low bright-face fraction (`_bright_frac`, V>200), not edge density. Bomb = `_dark_frac`.
- `count_pips` is routed per die type. Light↔Bubble tie-break by white fraction.
- Screen-state helpers shared by all bots: `is_battle` (green summon button), `is_game_over`,
  `is_lobby`, `has_popup_close`, `has_modal_x`, `is_exit_dialog`, `is_coop_room`, `read_speed` (Tesseract).
- `_debuff_cast` (gray-world WB for yellow cast) and `board_glare` are still board-global.

## tracker.py (docs/07 Layer A, done)
- Obs conf < `ABSTAIN` 0.50 ignored; belief changes after K equal reads (K=3; 8 Predator / 5 Light on
  a correct fixed cell); action-aware resets (switch swaps beliefs, merge/destroy frees source,
  summon onto empty accepted at once). Uncertain cells are passed to the planner as locked.

## Evidence
- `src/rdom/perception/board.py` — `COLS/ROWS`, `classify_type`, `CONF_MIN/MARGIN_MIN/LOW_CONF`, `is_battle`, `_debuff_cast`, `board_glare`
- `src/rdom/perception/tracker.py` — `ABSTAIN`, `K_NORMAL`, `K_PROTECT`, docstring
- `tests/test_tracker.py` — gate tests for the guarantees above
- `docs/07_RECOGNITION_REVIEW.md` — STATUS (Layer A implemented; B/C not started)
- `docs/01_GAME_SPEC.md` — M0 grid measurement
