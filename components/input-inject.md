---
title: Input injection (M2)
type: component
updated: 2026-10-23
sources: [seed]
---
# Input injection (M2)

`Injector` turns policy actions into taps/swipes posted as window messages to the Google Play Games
render child (`CROSVM_1`); it is dry-run by default and only injects with `execute=True`.

## How it works
- No adb on GPG: `WM_MOUSEMOVE/LBUTTONDOWN/UP` and `WM_KEYDOWN/UP` (Esc = Android BACK) are
  `PostMessage`d to the render child. Cursor is not moved, focus not needed.
- (u,v) → screen px of the same content rect the capture grabs → `ScreenToClient(render)`.
  ±4 px position jitter and randomised press/drag durations are added.
- Ops: `summon`, `destroy` (cell → Cheong, 90 s cooldown tracked here), `switch`, `merge`,
  `merge_destroy`; `align_pip`/`wait` are no-ops. Switch swaps are NOT timer-gated (cooldown varies);
  the caller verifies by re-reading the board.
- Named UI coordinates live here (`SUMMON_UV`, `CHEONG_UV`, `SPEED_UV`, lobby/coop/room buttons,
  `CLOSE_X_UV`, `MODAL_X_UV`, `CANCEL_UV`). Gear-deck tap targets are in `perception/gear.py` `UI`.
- `game_in_front()` / `launch_game()` (GPG URI) restart a closed game; return `None`/no-op in dry-run.

## Evidence
- `src/rdom/input/inject.py` — module docstring, `Injector.tap/swipe/back/execute_action`, UV constants
- `docs/01_GAME_SPEC.md` — "adb 없음 → 입력은 CROSVM_1에 PostMessage"
- `CLAUDE_CODE_TODO.md` — M2 line (original adb tap/swipe, 1440×2560, dry-run default)
