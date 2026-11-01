---
title: Input injection (M2)
type: component
updated: 2026-11-01
sources: [seed, rdf04-t2, rdf04-r1-s5]
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

## Backends: Injector (GPG) and AdbInjector (LDPlayer)
- `_ActionBase` holds `execute_action` and the Cheong / switch cooldown logic once; `Injector` and
  `AdbInjector` both subclass it (no duplicate copy). `make_injector(config_path, execute=False)` returns
  `AdbInjector` when the config's `[input] backend == "adb"` (`config/recorder_ld.toml`), else `Injector`.
- `AdbInjector` is dry-run by default (prints `[dry-run] input tap ...`, runs nothing). Taps/swipes go through
  `adb -s <serial> shell input ...`; `back()` = `input keyevent 4`; `launch_game()` = `am start -n
  com.percent.aos.randomdice2/com.unity3d.player.UnityPlayerActivity` (`monkey` is missing on LDPlayer 14).
  `game_in_front()` reads `dumpsys window` `mCurrentFocus` -> True/False, `None` in dry-run or on adb failure.
  `_out` returns `""` (= unknown -> `None`) on `TimeoutExpired` and on `OSError` / `FileNotFoundError`
  (adb.exe missing or crashing at spawn), so `game_in_front` never raises.
- adb path and preferred serial come from the config `[input]` keys. With `execute=True` the constructor runs
  `resolve_device` (preferred serial if attached, else the single attached device, else RuntimeError) and reads
  `wm size` once (an `Override size` line beats `Physical size`); unreadable -> prints
  `adb: wm size unreadable -- using 1440x2560` and uses 1440x2560. (u,v) -> px is jittered ±5 and clamped.
- **No pipes to adb.** `capture_output`/`PIPE` deadlocked a live run for 12 minutes (2026-09-27): the adb
  fork-server inherits the pipe handles, so Python waits for EOF forever and `timeout` does not help. `_run`
  sends stdout/stderr to DEVNULL; `_out` and `resolve_device` read via a temp file. Tests assert the
  stdout/stderr args of every faked adb call.
- A hard-coded serial that is not attached made every tap fail silently (2026-10-07), hence `resolve_device`.
- Restored from `3a70f61^` (the pre-GPG version); its tests fake `subprocess.run` (no real adb).

## Evidence
- `src/rdom/input/inject.py` — module docstring, `Injector.tap/swipe/back/execute_action`, UV constants
- `src/rdom/input/inject.py` — `_ActionBase`, `AdbInjector` (`_run`/`_out` comments, `wm size` fallback), `resolve_device`, `parse_wm_size`, `make_injector` (commit `3635c90`, rdf04-t2)
- commit `3635c90` (task/rdf04-t2) — adds the adb injector tests: dry-run, no-PIPE, wm size, resolve_device, make_injector cases
- `src/rdom/input/inject.py` — `AdbInjector._out` catches `(TimeoutExpired, OSError)` and returns `""` (rdf04-r1-s5)
- commit `e24d043` (task/rdf04-r1-s5) — adds `test_game_in_front_none_when_adb_cannot_run` (OSError, FileNotFoundError, Timeout -> None)
- `docs/01_GAME_SPEC.md` — "adb 없음 → 입력은 CROSVM_1에 PostMessage"
- `CLAUDE_CODE_TODO.md` — M2 line (original adb tap/swipe, 1440×2560, dry-run default)
