---
title: Safety guards and stop switches
type: component
updated: 2026-11-01
sources: [seed, rdf04-t8]
---
# Safety guards and stop switches

The bot only acts on a verified battle frame in an unmoved window, never injects unless asked, and
stops instead of looping blindly when something is systematically wrong.

## Guards
- **Dry-run default**: `Injector(execute=False)`; `tools/bot_live.py` and `tools/gear_bot.py` need `--execute`.
- **Window moved → stop**: `LiveGrabber.window_moved()` checked in `gear_loop`, `gear_bot`, `bot_live`, `play`.
- **Not a battle → no action**: `is_battle` (green summon button) gates board actions; menus/misreads blocked.
- **Read stability**: gear bot needs two identical consecutive reads before a board action, and ≥3
  post-초월 gear colours on two reads before treating the field as transcended; a merge whose cells did
  not change is banned until either die changes. Predator bot plans on tracker beliefs, uncertain cells locked.
- **Failure limits**: `gear_loop.py` stops after 3 consecutive rounds that fail to start, with a Discord status and screenshot, and exits 3 (guard) vs 0 (clean STOP) vs exception (crash), see [gear-loop](gear-loop.md); `data/STOP` is never deleted by it; `supervisor.py` restarts a
  crashed loop but gives up after 5 crashes in 30 min (Discord status + screenshot).
- **Pause/stop between games**: `data/PAUSE` (봇 일시정지.bat / Discord /정지) and `data/STOP`
  (/종료) are checked only between games, so a game in progress always finishes.
- **Hard recognition gate (planned)**: no live use of a new recognizer until held-out effect-crop
  accuracy ≥ 0.9 (`tools/eval_hard.py`, not yet written).

## Evidence
- `src/rdom/input/inject.py` — `execute=False` default
- `tools/gear_bot.py` — docstring (two identical reads, merge ban), `window_moved` check
- `tools/gear_loop.py` — PAUSE/STOP handling, `fails >= 3`
- `tools/supervisor.py` — 5 crashes / 1800 s rule
- `CLAUDE_CODE_TODO.md` — "안전 가드" item and "하드 평가셋 게이트"
