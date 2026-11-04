---
title: Content-normalised (u,v) coordinates; window messages instead of adb
type: decision
updated: 2026-11-05
sources: [seed, rdT07]
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
- Inject via `PostMessage` to the `CROSVM_1` render child (no cursor move).
  `docs/00_PRE_RESEARCH.md` §3.3 had rated PostMessage unreliable; on GPG it was verified to work.
- **Two GPG instances (rdT07, Master's probe 2026-11-05): background input is NOT possible.** A posted
  click to the render child of the non-foreground window was ignored 3 of 3; sending
  `WM_ACTIVATEAPP`, `WM_NCACTIVATE`, `WM_ACTIVATE` (1,0) to the top window and `WM_SETFOCUS` to the render
  child first made it work 2 of 2 and made that window the real foreground window; each message alone did
  not. So every `Injector` gesture takes the named mutex `Local\rdom_input` (the two bot processes take
  turns, a drag is never cut), activates its window, posts, releases. Accepted side effect: the game
  windows take the foreground on every input while the bots run. Capture of a background window is fine.

## Consequences
- Chrome insets and window size are fixed config; moving/resizing the window stops the bot.
- Old LDPlayer values (chrome 0/40/39/0, adb 127.0.0.1:5555) are historical only.

## Evidence
- `src/rdom/input/inject.py` — docstring (two-instance finding), `_lock/_activate/_gesture` and `_point()` (commit `c5aec51`, rdT07)
- `src/rdom/capture/live.py` — `content_rect()` uses the same `Viewport`/`fit_chrome`
- `config/recorder.toml` — `[target.chrome]` comment (GPG 2026-10-16; LDPlayer values)
- `docs/01_GAME_SPEC.md` — emulator section
- `docs/05_AMENDMENTS.md` — A1, A2
- `CLAUDE_CODE_TODO.md` — M2 line (adb, 1440×2560)
