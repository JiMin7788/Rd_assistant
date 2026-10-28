---
title: Live screen capture
type: component
updated: 2026-10-29
sources: [seed, rdf01-t6]
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

## Unobscured check and support writers (R5)
- `LiveGrabber.unobscured()` = `not rects_cover(content, windows_above(hwnd))`; any exception -> `False`
  (fail closed). `rects_cover` needs a positive overlap area (touching edges do not count).
- `windows_above` walks `GetWindow(GW_HWNDPREV)` and skips invisible, iconic, DWM-cloaked, zero-area,
  `WS_EX_LAYERED|WS_EX_TRANSPARENT` (click-through overlays) and `Shell_TrayWnd`/`Shell_SecondaryTrayWnd`;
  otherwise an overlay or the taskbar would mark the game covered forever. Verified only by inspection/pure
  tests, not yet on the user's PC (H1 step 2).
- `perception/collect.py`: `save_support_cells(frame, game_id, t, unobscured, buffed, glare)` writes 15
  cells at 72 px (`_raw/`) and 128 px (`_hires/`) plus `crops.jsonl` lines under `data/crops_support/`;
  `save_frame(frame, path, unobscured)` writes a PNG, returns path or `None`. Both write nothing when
  covered and print `frame not saved: game window covered` at most once per 60 s; neither raises.
  Not called from any bot loop yet. The older `maybe_save`/`save_fail` still have no covered check.
- `tools/save_frame.py` saves one manual frame to `data/support_frames/manual/`; exit 1 if covered.

## Invariants
- Changing chrome/window size invalidates coordinates and the recorder's env fingerprint
  (see `docs/05_AMENDMENTS.md` A1/A2). Re-measure with `tools/verify/g2b_chrome.py`.

## Evidence
- `src/rdom/capture/live.py` — `LiveGrabber`, `place_game_window`, `_grab_region` retry spacing, `_grab_watchdog`
- `src/rdom/capture/live.py` — `rects_cover`, `windows_above`, `LiveGrabber.unobscured`
- `src/rdom/perception/collect.py` — `save_support_cells`, `save_frame`, `_covered_warn`
- task rdf01-t6 branch (not yet merged into the main checkout): tools/save_frame.py manual frame saver, tests/test_support_collect.py writer/rects tests
- `config/recorder.toml` — `[target]`, `[target.chrome]`, `[target.place]`, `monitor_index = 1`
- `docs/01_GAME_SPEC.md` — emulator section (GPG since 2026-10-16, chrome 132/72)
- `docs/05_AMENDMENTS.md` — A1 chrome insets, A2 capture covers content
