---
title: Input injection (M2)
type: component
updated: 2026-11-05
sources: [seed, rdf04-t2, rdf04-r1-s5, rdf05-t3, rdT07, rdT10, rdT11]
---
# Input injection (M2)

`Injector` turns policy actions into taps/swipes posted as window messages to the Google Play Games
render child (`CROSVM_1`); it is dry-run by default and only injects with `execute=True`.

## How it works
- No adb on GPG: `WM_MOUSEMOVE/LBUTTONDOWN/UP` and `WM_KEYDOWN/UP` (Esc = Android BACK) are
  `PostMessage`d to the render child. Cursor is not moved.
- **Activation + cross-process lock (rdT07).** With two GPG windows a post to the non-foreground window is
  ignored (Master's probe 2026-11-05: 3 of 3 ignored; activation first: 2 of 2 worked). In execute mode
  `tap`, `swipe` and `back` run inside `Injector._gesture()`: `WaitForSingleObject` on the named mutex
  `Local\rdom_input` (`INPUT_MUTEX`, `LOCK_TIMEOUT_MS` 5000; on timeout the gesture is logged and
  skipped), then `_activate()` = `SendMessageW(top, WM_ACTIVATEAPP, 1, 0)`, `WM_NCACTIVATE`, `WM_ACTIVATE`,
  `SendMessageW(render, WM_SETFOCUS, 0, 0)`, check `GetForegroundWindow() == top` (else
  `SetForegroundWindow(top)`, one log line if it still fails), `SETTLE_S` 0.03 s settle, then the posts,
  and `ReleaseMutex` in a `finally` (also when posting raises). The lock covers the whole swipe. Dry run
  does none of it. Probe 2026-11-05, exactly: the four-message sequence worked and made the window the
  foreground window; variants that did not change the foreground window were WM_SETFOCUS only, WM_ACTIVATEAPP
  only, WM_NCACTIVATE only and WM_ACTIVATE+WM_SETFOCUS on the render child. Nothing else was tried.
  The joiner's accept tap (`coop_join.wait_and_accept`, `tap` -> `inj.tap`) goes through the same
  `Injector`, so it is activated and locked too. Tests: `tests/test_rdt07_input_lock.py`.
- **Real-foreground wait, fair lock, gesture trust (rdT10)** replaces the `SETTLE_S` 0.03 s tail above (it let
  joiner accept taps be swallowed). `_activate()` returns at once when `GetForegroundWindow() == top`.
  Otherwise it counts a switch, sends the four messages, and if still not in front calls `_force_foreground`
  (AttachThreadInput to the foreground thread, synthetic ALT down/up, SetForegroundWindow + BringWindowToTop).
  It then polls every `FG_POLL_S` 0.02 s up to `FG_POLL_MAX_S` 0.6 s; once in front it sleeps
  `ACTIVATE_SETTLE_S` 0.15 s before the first post. Never in front -> returns False (the "did not become the
  foreground window" line is limited to one per `FG_WARN_EVERY_S` 60 s).
  Posts still go out when the window never came to front; `last_gesture_ok` (default True; False after a
  lock timeout or unconfirmed foreground) tells the caller the gesture is untrustworthy. `AdbInjector` and
  dry run keep `last_gesture_ok` True and have no stats.
- **Foreground lease (rdT11)** replaces rdT10's `LOCK_YIELD_S` sleep (removed). The mutex alone was released
  after every gesture, so two bots acting at once flipped the foreground on almost every gesture (live run:
  ~470 gestures and ~170 switches per bot per round). The lease is a 64-byte named shared memory
  (`mmap.mmap(-1, 64, tagname=LEASE_TAG "rdom_input_lease")`, `_LeaseStore`, struct `<IIdd` = owner pid,
  waiting pid, lease_until, owner_since in monotonic seconds), read/written only while holding the mutex.
  `_take_turn` loops: take the mutex with the time left of `LOCK_TIMEOUT_MS` (the whole lease wait counts
  against it; on timeout the gesture is skipped as before), read the lease, `_must_wait`; if free become owner
  (`owner_since` = now when the owner changed or the lease had expired) and go on holding the mutex; else set
  `waiting` = our pid, release the mutex, sleep `LEASE_POLL_S` 0.02 s, retry. A foreign lease blocks only while
  `lease_until > now`, the owner's turn is younger than `QUANTUM_S` 2.5 s and `_pid_alive(owner)`
  (OpenProcess/GetExitCodeProcess), so an expired lease or dead owner never blocks. After each gesture `_renew`
  (mutex held) sets `lease_until = now + HOLD_S` 0.8 s (a burst: power-panel taps, consecutive merges); once
  the owner's turn is older than `QUANTUM_S` and a live other pid waits it does not renew, and its next gesture
  waits for the other bot (`_must_wait` owner branch). If the shared memory cannot be opened it prints
  `input lease unavailable ... -- mutex only` and falls back to the mutex alone. Tests use a fake lease store.
- **Switch timing stats (rdT11).** `Injector.stats` = gestures / switches / not_foreground / lock_timeouts plus
  `ready_ms_total/max` (gesture start -> posting, i.e. lock + lease wait + activation, all gestures) and
  `waited` / `waited_ms_total/max` (gestures that had to wait for the other bot's lease).
  `gear_loop.log_input_stats` prints them once per round and resets: `input: N gestures, N switches, N not in
  front, N lock timeouts, waited N (avg X ms, max Y ms), start-to-post avg X ms, max Y ms`.
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

## Press / release / cancel (rdf05-t3, not wired)
For the 멈춰 button, which registers on mouse UP. Both injectors expose `press(u, v, clamp=None)` ->
`perf_counter()` after posting, `release()`, `cancel()`, `press_lead`, `uses_swipe`, `start_delay()` and
`release_swipe(t_release, clock, sleeper)`. In dry-run each only prints `[dry-run] press/release/cancel`
and touches neither the window nor adb.
- **GPG** (`Injector`): `press` posts MOUSEMOVE + LBUTTONDOWN and keeps the point; `release` posts
  LBUTTONUP at that same point (None if nothing is held); `cancel` posts 6 `MK_LBUTTON` moves down to
  `v + CANCEL_DV` (0.12), then UP there. `press_lead` = `PRESS_LEAD_GPG` 0.25 s, `start_delay()` 0.
  `release_swipe` raises NotImplementedError. `_point(..., clamp=(u0,v0,u1,v1))` keeps the jittered
  point inside that content box.
- **LD** (`AdbInjector`): `probe_release_method()` (cached) runs read-only `getevent -pl`, picks the first
  device with ABS_MT_POSITION_X/Y that `test -w` says is writable -> `("sendevent", dev, (max_x, max_y))`,
  else `("swipe", None, None)`; it also times 5 `adb shell true` calls and keeps the median as
  `_spawn_delay`. A dry run reports the swipe default without probing or caching. `method_line()` gives
  the status line `LD 입력 방식: sendevent (<dev>)` or `... input swipe (정확도 낮음)`.
- sendevent: press/release/cancel each spawn one non-waiting `adb shell "sendevent ...; ..."` (DEVNULL,
  never PIPE; finished Popens are reaped on the next spawn); cancel = move to `v + CANCEL_DV` then UP in one
  call. Coordinates scale to the device's own axis max, not `wm size`.
- swipe fallback: a touch cannot be held, so `press` only stores the point and `release`/`cancel` return
  None. `release_swipe` spawns `input swipe x y x y 600` (`PRESS_LEAD_LD` 0.6 s) at
  `t_release - start_delay() - PRESS_LEAD_LD`, sleeping until then, and returns None without sending when
  that time has already passed. `start_delay()` = `_spawn_delay` only on the swipe method.
- `PRESS_LEAD_GPG` / `PRESS_LEAD_LD` are chosen constants, not measured; calibrate them live (see
  [policy-minigame](policy-minigame.md) LatencyCal).

## Evidence
- `src/rdom/input/inject.py` (rdT11, task/rdT11) — `LEASE_TAG`, `HOLD_S`, `QUANTUM_S`, `LEASE_POLL_S`, `_LeaseStore`, `_pid_alive`, `Injector._must_wait/_take_turn/_renew/_gesture`, the extended `stats`, the module docstring with the probe variants; `LOCK_YIELD_S` is gone; tests in `tests/test_rdt07_input_lock.py`.
- commit `9c8ce09` (rdT10) — `src/rdom/input/inject.py` `ACTIVATE_SETTLE_S`, `FG_POLL_S`, `FG_POLL_MAX_S`, `FG_WARN_EVERY_S`, `LOCK_YIELD_S`, `Injector._force_foreground/_activate/_gesture`, `last_gesture_ok`, `stats`; tests in `tests/test_rdt07_input_lock.py`.
- commit `c5aec51` (rdT07) — `src/rdom/input/inject.py` `INPUT_MUTEX`, `LOCK_TIMEOUT_MS`, `SETTLE_S`, `Injector._lock/_activate/_gesture`, `tap/swipe/back` inside `_gesture()`; the same commit adds the input-lock test file (fake user32/kernel32; on task/rdT07, not in this checkout until merge, so not lint-checked). `press/release/cancel` were not changed by rdT07 (no lock/activation there).
- `src/rdom/input/inject.py` — `Injector.press/release/cancel/release_swipe`, `_point(clamp=)`, `PRESS_LEAD_*`, `CANCEL_DV`; `AdbInjector.probe_release_method/_release_method/press/release/cancel/release_swipe/_spawn`, `parse_getevent`, `method_line` (commit `5152657`, rdf05-t3)
- commit `5152657` (task/rdf05-t3) — adds the test_inject_press tests: press/release/cancel messages and sendevent/swipe command cases
- `src/rdom/input/inject.py` — module docstring, `Injector.tap/swipe/back/execute_action`, UV constants
- `src/rdom/input/inject.py` — `_ActionBase`, `AdbInjector` (`_run`/`_out` comments, `wm size` fallback), `resolve_device`, `parse_wm_size`, `make_injector` (commit `3635c90`, rdf04-t2)
- commit `3635c90` (task/rdf04-t2) — adds the adb injector tests: dry-run, no-PIPE, wm size, resolve_device, make_injector cases
- `src/rdom/input/inject.py` — `AdbInjector._out` catches `(TimeoutExpired, OSError)` and returns `""` (rdf04-r1-s5)
- commit `e24d043` (task/rdf04-r1-s5) — adds `test_game_in_front_none_when_adb_cannot_run` (OSError, FileNotFoundError, Timeout -> None)
- `docs/01_GAME_SPEC.md` — "adb 없음 → 입력은 CROSVM_1에 PostMessage"
- `CLAUDE_CODE_TODO.md` — M2 line (original adb tap/swipe, 1440×2560, dry-run default)
