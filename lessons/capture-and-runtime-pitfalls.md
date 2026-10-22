---
title: Capture and runtime pitfalls
type: lesson
updated: 2026-10-23
sources: [seed]
---
# Capture and runtime pitfalls

Coordinate and capture bugs here are silent: data stays self-consistent while being wrong, or the bot
just stalls. These are the ones that already bit.

## Pitfalls
- **Emulator chrome inside "content"**: LDPlayer's top tab bar (40 px) was counted as game, shifting
  (u,v) origin and scaling v by 1.019 — no check caught it. Chrome is now fixed config, never auto-detected.
- **Forced output resolution squashed video** 21% horizontally for 43 min with no warning → output
  size derived from the capture aspect.
- **Horizontal stretch**: LDPlayer stretched the 9:16 surface; fixed by sizing the window to 9:16.
- **dxcam returns None for an unchanged screen**; back-to-back retries all return None and the caller
  reused a stale frame (the speed check read the speed from before its own tap) → spaced retries.
- **dxcam can block forever** when its duplication device is lost (minimised window, display change)
  → watchdog thread + camera rebuild.
- **Tap jitter vs small buttons**: the old speed-button point sat near the rim, ±px jitter missed it →
  re-measured to the disc centre (0.781, 0.799).
- **Lobby popups**: shop popups must be closed with their X; BACK on the lobby root opens the quit dialog.
- **Cowork cannot run local shell** (device_bash mount broken since 2026-09-08) and has no PyPI;
  local execution happens in Claude Code.

## Evidence
- `docs/05_AMENDMENTS.md` — A1 (chrome), A2 (out_res), A6 (stretch)
- `docs/01_GAME_SPEC.md` — stretch resolved by 9:16 window
- `src/rdom/capture/live.py` — `_grab_region`, `_grab_watchdog` comments (2026-09-27)
- `src/rdom/input/inject.py` — `SPEED_UV`, `CLOSE_X_UV` comments
- `CLAUDE_CODE_TODO.md` — "환경 / 인프라"
