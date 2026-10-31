---
title: Start check (preflight) and duo_check
type: component
updated: 2026-11-01
sources: [rdf04-t7]
---
# Start check (preflight) and duo_check

`capture/preflight.py` `check(profile_names, place=True, grab=False)` tells whether each game window is
there, placed, uncovered and (LD) reachable by adb; `tools/duo_check.py` runs it for both windows plus a
concurrent one-frame grab. Neither injects input or saves a frame. Not called from any bot loop yet.

## check()
- Returns `[(name, ok, reason)]`; per profile the first failing step ends it, in this order: window found
  exactly once, `place_game_window` (only if `place`), `LiveGrabber.unobscured()`, adb probe (only when
  `cfg.input.backend == "adb"`, so never for gpg), optional one-frame `grab()` (`grab=True`).
- Window lookup uses `recorder.window.find_window`; its `RuntimeError` is split by message: starts with
  `N windows match` -> `MANY` ("<title_re> 창이 2개 이상이에요"), anything else -> `MISSING[name]`.
  This depends on the wording of that error text.
- With two profiles and both passed, a last entry `("overlap", ...)` compares the two content rects with
  `live.rects_cover` ("두 게임 창이 겹쳐요" / "두 게임 창이 겹치지 않아요"). Touching edges do not count.
- Reason texts are module constants (`MISSING`, `MANY`, `COVERED`, `NO_ADB`, `OVERLAP`); success reason is
  `<LABEL> 준비됐어요`. `format_lines` gives `start check: OK|FAIL <reason>`.
- Seams for tests: `finder`, `placer`, `grabber_factory`, `adb_probe`. Grabbers are closed in `finally`.
- `adb_probe(adb, serial)`: `resolve_device`, then `adb -s <dev> shell wm size` with stdout to a temp file
  (never a pipe: adb pipes deadlock on Windows), True if `parse_wm_size` parses. Read-only; any
  RuntimeError/OSError/SubprocessError -> False.

## tools/duo_check.py
- Runs `check(["ld","gpg"], place=True)`; only if all pass, spawns two child processes (`--grab <name>`,
  hidden flag) that each `LiveGrabber(...).grab()` and print the shape. Both are started before either is
  waited on, so the two dxcam duplications of one output really overlap (architecture risk §13).
- Prints only start-check lines; exit 0 only when every line is OK. Running it on the live windows is the
  H4 human step (not done by the task).

## Evidence
- task rdf04-t7 branch (not yet merged into the main checkout), commit `c3e1e0d`: capture/preflight.py (`check`, `_find_reason`, `adb_probe`, reason constants, `format_lines`), tools/duo_check.py (`main` starts both `spawn` calls before any `communicate`; `_grab_one`, `--grab` child mode), tests/test_preflight.py (fakes for every seam; exact lines per failure, overlap, adb only for backend adb)
- `src/rdom/capture/live.py` — `rects_cover`, `unobscured` used by the check (see [capture-live](capture-live.md))
