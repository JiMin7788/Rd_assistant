---
title: Content-normalised (u,v) coordinates; window messages instead of adb
type: decision
updated: 2026-10-23
sources: [seed]
---
# Content-normalised (u,v) coordinates; window messages instead of adb

All positions are content-normalised (u,v) in [0,1] over the game content rect (client − chrome).
Since 2026-10-16 input is posted as window messages to Google Play Games; adb is no longer used.

## Context
- Recording schema v2 (`docs/05_AMENDMENTS.md` A1/A2) defined content = client − chrome − letterbox
  and captured only the content, so recorded action (u,v) map linearly onto video pixels.
- M2 first shipped on LDPlayer 14 via adb: (u,v) → android 1440×2560 directly. Taps/swipes were
  verified live on 2026-09-16.
- On 2026-10-16 the emulator changed to Google Play Games (PC), which has no adb.

## Choice
- Keep (u,v) as the single coordinate space for perception, policy and input; capture and input both
  derive the content rect from the same `[target.chrome]` config, so a (u,v) read off a frame is tapped
  back at the same spot.
- Inject via `PostMessage` to the `CROSVM_1` render child (works in background, no cursor/focus).
  `docs/00_PRE_RESEARCH.md` §3.3 had rated PostMessage unreliable; on GPG it was verified to work.

## Consequences
- Chrome insets and window size are fixed config; moving/resizing the window stops the bot.
- Old LDPlayer values (chrome 0/40/39/0, adb 127.0.0.1:5555) are historical only.

## Evidence
- `src/rdom/input/inject.py` — docstring and `_point()`
- `src/rdom/capture/live.py` — `content_rect()` uses the same `Viewport`/`fit_chrome`
- `config/recorder.toml` — `[target.chrome]` comment (GPG 2026-10-16; LDPlayer values)
- `docs/01_GAME_SPEC.md` — emulator section
- `docs/05_AMENDMENTS.md` — A1, A2
- `CLAUDE_CODE_TODO.md` — M2 line (adb, 1440×2560)
