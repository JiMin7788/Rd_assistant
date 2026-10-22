---
title: Live screen capture
type: component
updated: 2026-10-23
sources: [seed]
---
# Live screen capture

`LiveGrabber` grabs exactly the game's content rect (client − chrome) with dxcam and returns an RGB
ndarray, so frame pixels map 1:1 to content-normalised (u,v) — the same space input uses.

## How it works
- Window found by `[target].window_title_re` (`^랜덤 다이스 2`, Google Play Games); content =
  client − `[target.chrome]` (left 132, top 72 on GPG, measured 2026-10-16) via `geometry.fit_chrome`.
- dxcam output = `[capture].monitor_index` (1 = DISPLAY2, where the GPG window sits).
- `place_game_window()` moves the window to `[target.place]` at bot start.
- `window_moved()` compares against the window state captured at construction (safety guard).
- dxcam returns `None` for an unchanged screen; `grab()` then returns the last frame. Retries are
  spaced ~8 ms so a fresh frame arrives instead of a stale one.
- Watchdog: each grab runs on a worker thread; if it hangs > `grab_timeout` (8 s) the camera is
  dropped and rebuilt once; a second hang raises.

## Invariants
- Changing chrome/window size invalidates coordinates and the recorder's env fingerprint
  (see `docs/05_AMENDMENTS.md` A1/A2). Re-measure with `tools/verify/g2b_chrome.py`.

## Evidence
- `src/rdom/capture/live.py` — `LiveGrabber`, `place_game_window`, `_grab_region` retry spacing, `_grab_watchdog`
- `config/recorder.toml` — `[target]`, `[target.chrome]`, `[target.place]`, `monitor_index = 1`
- `docs/01_GAME_SPEC.md` — emulator section (GPG since 2026-10-16, chrome 132/72)
- `docs/05_AMENDMENTS.md` — A1 chrome insets, A2 capture covers content
