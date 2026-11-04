---
title: Supervisor (duo / gear modes)
type: component
updated: 2026-11-05
sources: [rdf04-t9, rdf04-t10, rdT06, rdT07]
---
# Supervisor (duo / gear modes)

`tools/supervisor.py` runs one or two `gear_loop.py` children, restarts a crashed bot, and stops both bots on a guard stop or a bot's 5th crash in 30 minutes. Started by `run_all.py` with an explicit `--mode` ([run-all](run-all.md)).

## Modes and children
- `--mode duo` (default, since rdT06): two gear bots on two Google Play Games windows: `gear_loop.py --profile gpg --role inviter --execute` (tag [기어1]) and `--profile gpg2 --role joiner --execute` (tag [기어2]). `--mode gear`: only `--profile gpg --role public --execute`. The table is `CHILDREN`; tags come from `rdom.profile`.
- `Supervisor(mode, data_dir, spawn, clock, sleep, notify, screenshot)` takes everything injectable, so tests use fake children and a tmp data dir. Module import has no side effects: pid file, `bot_mode.json` and `room.json` are written in `run()` only.
- Each (re)start gets a new log `data/bot_logs/YYYYMMDD_HHMM_<profile>.log` (`gpg` / `gpg2`; named by profile because both duo bots are bot `gear`); a restart inside the same minute gets `_2`, `_3` so the log of the crash just reported is not overwritten.

## Exit handling (poll every 1 s)
- Exit 0: that child is done. Exit 3 (guard): stop-both. Anything else: crash.
- Crashes are counted **per bot** in a 1800 s deque. Under 5: notify `⚠ [<tag>] 봇 오류로 재시작 (<n>/5)` + last 6 log lines + that bot's screenshot, restart after 10 s. The 5th: stop-both with the `⛔ ... 30분 안에 5번 오류` text (gear mode has its own wording) + tail + screenshot.
- Stop-both writes `data/STOP`, cancels pending restarts, never restarts afterwards, waits for every child (the other bot finishes its current game), notifies `■ 두 봇 모두 정지됨` (duo only) and returns 1. A guard stop in duo also notifies `⛔ [<tag>] 봇이 멈춰서 두 봇 모두 정지 ...`; in gear mode it is silent here because the child already reported it.
- All children exit 0 -> return 0. On any exit `supervisor.pid`, `bot_mode.json` and `STOP` are removed (`finally`).

## Single instance (rdT07)
`main` calls `running_supervisor(data/supervisor.pid)` first; another live python pid there -> prints `이미 실행 중이에요 -- 두 번째 실행은 무시합니다 (pid N)` and returns 2, nothing started (`Supervisor.run` is unchanged; tests drive it directly). Covers run_all and Discord `/시작` alike (2026-11-05 two stacks ran at once, two bots per window). Test: `tests/test_rdt07_input_lock.py::test_supervisor_refuses_second_copy`.

## Files written
- `data/supervisor.pid` (read by `discord_bot.running()`), `data/bot_mode.json` `{mode, bots:[{bot, tag, profile, pid}], t}` rewritten atomically on every (re)start so pids stay current, and in duo `room.json` `{code: null, state: 'duo'}` via `room_state.write_room`.
- Status texts are constants (`RESTART_TEXT`, `LIMIT_TEXT_*`, `GUARD_TEXT`, `ENDED_TEXT`) matching spec.md.

## Evidence
- commit `c5aec51` (rdT07) — `tools/supervisor.py` `running_supervisor` and the `return 2` refusal in `main`.
- `tools/supervisor.py` — `CHILDREN`, exit-code constants, text constants, `Supervisor._exited` / `_stop_both` / `run`, `_log_path` collision suffix, `_write_mode`.
- `tools/gear_loop.py` — exit 0/3/crash contract the supervisor relies on (see [gear-loop](gear-loop.md)).
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `tools/supervisor.py` `CHILDREN` (duo = gpg inviter + gpg2 joiner, both gear) and `_log_path` (profile-named logs); tests/test_supervisor_duo.py asserts the children.
- rdf04-t9 diff (the supervisor duo test file added on the task branch) — fake-child tests for per-bot crash counts, stop-both, files at exit.
