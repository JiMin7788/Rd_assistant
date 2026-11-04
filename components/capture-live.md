---
title: Live screen capture
type: component
updated: 2026-11-05
sources: [rdf02-t7, seed, rdf01-t6, rdf02-t5, rdf05-t4, rdT07, rdT08]
---
# Live screen capture

`LiveGrabber` grabs exactly the game's content rect (client − chrome) with dxcam and returns an RGB
ndarray, so frame pixels map 1:1 to content-normalised (u,v) — the same space input uses.

## How it works
- Window found by `[target].window_title_re`; with two Google Play Games windows these are two EXACT titles
  (rdT07, swapped by rdT08): `^랜덤 다이스 2 - CumbersomeTutor145$` in `config/recorder.toml` (profile gpg,
  대변먹는자 inviter) and `^랜덤 다이스 2 - CleanCardinal77$` in `config/recorder_gpg2.toml` (gpg2, 배속봇
  joiner), so neither pattern
  matches the other window or the launcher. Capture of a background window keeps working (it keeps
  animating); only input needs the window activated ([input-inject](input-inject.md)). Content =
  client − `[target.chrome]` (left 132, top 72 on GPG, measured 2026-10-16) via `geometry.fit_chrome`.
- dxcam output = `[capture].monitor_index` (1 = DISPLAY2, where the GPG window sits).
- `place_game_window()` moves the window to `[target.place]` at bot start.
- `window_moved()` compares against the window state captured at construction (safety guard).
- dxcam returns `None` for an unchanged screen; `grab()` then returns the last frame. Retries are
  spaced ~8 ms so a fresh frame arrives instead of a stale one.
- Watchdog: each grab runs on a worker thread; if it hangs > `grab_timeout` (8 s) the camera is
  dropped and rebuilt once; a second hang raises.

## grab_fresh (timestamped, new frames only; rdf05)
- `grab_fresh(region_uv=None, retry_sleep=0.001)` -> `(ndarray | None, t)`. `region_uv` = (u0, v0, u1, v1) of
  the content rect (None = whole content), clamped to the content, converted to monitor-relative pixels
  like `grab()`; an empty box raises `ValueError`.
- It never returns the cached `_last` (unlike `grab()`): a repeated frame would look like a new sample when
  timing the minigame sweep. No new frame within ~40 ms (`tries = 0.040 / retry_sleep`) -> `(None, t)`.
- `t` = `time.perf_counter()` taken inside `_grab_region(timed=True)` right after dxcam returned, i.e. on
  the worker thread, not after the watchdog join. Spacing is 1 ms because 8 ms would be half a game
  frame of timestamp error.
- Runs through `_grab_watchdog(region, **kw)` (same rebuild-once-then-raise hang handling).
  `_grab_region` defaults (0.008 s, 30 tries) are unchanged, so `grab()` behaves as before.
- Not yet called by any loop (the minigame loop is a later task); tested with a fake camera only, no live
  dxcam.

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
- `save_burst(game_id, t, cells, grabs, unobscured, record)` saves every kept burst grab k of every listed
  cell as `<game>_<t:.1f>_<cell:02d>_<k>.png` at 72 px (`data/support_frames/_burst/_raw/`) and 128 px
  (`_burst/_hires/`), and appends `record` plus `"names"` (the 72 px names) to `_burst/bursts.jsonl`. Covered
  -> writes nothing and returns `None`; never raises (returns `None` on error). Called through `Saver.burst`
  by the burst code in [support-players](support-players.md).
- `tools/save_frame.py` saves one manual frame to `data/support_frames/manual/`; exit 1 if covered. It no
  longer goes through `collect.save_frame`: it checks `unobscured()` first (covered -> prints
  `not saved: game window covered`, no file), then `claim_file(folder, stamp)` creates `<stamp>.png`, else
  `<stamp>_2.png` ... `_99.png` with exclusive create (`'xb'`), so two saves in the same second (or from two
  processes) never overwrite. No free name -> `not saved: no free file name`, exit 1.

## Invariants
- Changing chrome/window size invalidates coordinates and the recorder's env fingerprint
  (see `docs/05_AMENDMENTS.md` A1/A2). Re-measure with `tools/verify/g2b_chrome.py`.

## Evidence
- `src/rdom/capture/live.py` — `LiveGrabber`, `place_game_window`, `_grab_region` retry spacing, `_grab_watchdog`
- `src/rdom/capture/live.py` — `grab_fresh`, `_grab_region(retry_sleep, tries, timed)`, `_grab_watchdog(**grab_kw)`
- commit `6fed322` (task rdf05-t4 branch, not yet merged into the main checkout), test_live_grab_fresh.py — box math with monitor offset, None not `_last`, stamp after frame, grab() fallback + 0.008 spacing, hung camera
- `src/rdom/capture/live.py` — `rects_cover`, `windows_above`, `LiveGrabber.unobscured`
- `src/rdom/perception/collect.py` — `save_support_cells`, `save_frame`, `save_burst` (paths, names, jsonl line, covered -> `None`), `_covered_warn`
- `tools/save_frame.py` — `claim_file` ('xb' exclusive create, `_2`..`_99` suffix), covered check before claiming
- commit `d4aff7c` (not yet merged into the main checkout), test_save_frame_tool.py — never-overwrite, skips pre-created suffix, exhausted -> `None`
- task rdf01-t6 branch (not yet merged into the main checkout): tests/test_support_collect.py writer/rects tests
- `config/recorder.toml`, `config/recorder_gpg2.toml` — `window_title_re` = CumbersomeTutor145 (gpg) / CleanCardinal77 (gpg2), commit rdT08 swap
- `config/recorder.toml` — `[target]`, `[target.chrome]`, `[target.place]`, `monitor_index = 1`
- `docs/01_GAME_SPEC.md` — emulator section (GPG since 2026-10-16, chrome 132/72)
- `docs/05_AMENDMENTS.md` — A1 chrome insets, A2 capture covers content
