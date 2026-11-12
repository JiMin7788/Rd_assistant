---
title: Supervisor (duo / gear modes)
type: component
updated: 2026-11-12
sources: [rdf04-t9, rdf04-t10, rdT06, rdT07, rdT15, rdT17]
---
# Supervisor (duo / gear modes)

`tools/supervisor.py` runs one or two `gear_loop.py` children, restarts a crashed bot, and stops both bots on a guard stop or a bot's 5th crash in 30 minutes. Started by `run_all.py` with an explicit `--mode` ([run-all](run-all.md)).

## Modes and children
- `--mode duo` (default, since rdT06): a gear bot and a support bot on two Google Play Games windows (rdT15): `gear_loop.py --profile gpg --role inviter --execute` (gear, tag [기어1]) and `--profile gpg2 --role joiner --execute` (gpg2 = support joiner, tag [서폿]). `--mode gear`: only `--profile gpg --role public --execute`. The table is `CHILDREN`; tags come from `rdom.profile`.
- `Supervisor(mode, data_dir, spawn, clock, sleep, notify, screenshot)` takes everything injectable, so tests use fake children and a tmp data dir. Module import has no side effects: pid file, `bot_mode.json` and `room.json` are written in `run()` only.
- **Solo window mode ("한 창 모드", rdT17).** In duo, `run()` first calls `_choose_windows()` once (after the pid file, before `bot_mode.json`): `missing(profile)` per child (default `window_missing`: only `preflight._find_reason` with `window.find_window`, read-only, no placement; several matching windows count as present so the child's own preflight reports them). Both present -> duo exactly as before. One present -> `mode = "solo"`, only that window's bot (its own kind: gpg gear, gpg2 support) with `--role solo --partner <other account>` (cmd `... --role solo --partner X --execute`): gpg alone = 대변먹는자 (duo.host) invites duo.partner 배속봇, gpg2 alone = 배속봇 invites duo.host 대변먹는자 (user 2026-11-12 '어느 창이든 혼자면 초대'); one line `▶ 한 창 모드: <name> 혼자 -- <partner> 초대` is printed and sent. None -> `⛔ 시작 점검 실패: <reasons joined by ' · '>`, nothing started, `run()` returns 1. The decision is not repeated on restarts.
- Solo with one child: restarts and the 5-crash limit work as before (`LIMIT_TEXT_SOLO` `⛔ <tag> 30분 안에 5번 오류 -- 봇 정지. 확인 필요`); a guard stop is silent here (the child reported it) and there is no `■ 두 봇 모두 정지됨`. `Supervisor(..., missing=, duo_cfg=)` are injectable; tests pass fake window results.
- Each (re)start gets a new log `data/bot_logs/YYYYMMDD_HHMM_<profile>.log` (`gpg` / `gpg2`; named by profile, not by bot kind, so the run_all / discord_bot log globs keep working); a restart inside the same minute gets `_2`, `_3` so the log of the crash just reported is not overwritten.

## Exit handling (poll every 1 s)
- Exit 0: that child is done. Exit 3 (guard): stop-both. Anything else: crash.
- Crashes are counted **per bot** in a 1800 s deque. Under 5: notify `⚠ [<tag>] 봇 오류로 재시작 (<n>/5)` + last 6 log lines + that bot's screenshot, restart after 10 s. The 5th: stop-both with the `⛔ ... 30분 안에 5번 오류` text (gear mode has its own wording) + tail + screenshot.
- Stop-both writes `data/STOP`, cancels pending restarts, never restarts afterwards, waits for every child (the other bot finishes its current game), notifies `■ 두 봇 모두 정지됨` (duo only) and returns 1. A guard stop in duo also notifies `⛔ [<tag>] 봇이 멈춰서 두 봇 모두 정지 ...`; in gear mode it is silent here because the child already reported it.
- All children exit 0 -> return 0. On any exit `supervisor.pid`, `bot_mode.json` and `STOP` are removed (`finally`).

## Single instance (rdT07)
`main` calls `running_supervisor(data/supervisor.pid)` first; another live python pid there -> prints `이미 실행 중이에요 -- 두 번째 실행은 무시합니다 (pid N)` and returns 2, nothing started (`Supervisor.run` is unchanged; tests drive it directly). Covers run_all and Discord `/시작` alike (2026-11-05 two stacks ran at once, two bots per window). Test: `tests/test_rdt07_input_lock.py::test_supervisor_refuses_second_copy`.

## Files written
- `data/supervisor.pid` (read by `discord_bot.running()`), `data/bot_mode.json` `{mode, bots:[{bot, tag, profile, pid}], t}` rewritten atomically on every (re)start so pids stay current (solo adds `mode: "solo"` and `solo: {profile, name, partner}`, read by Discord and run_all), and in duo and solo `room.json` `{code: null, state: 'duo'}` via `room_state.write_room` (an invite room, never a public code).
- Status texts are constants (`RESTART_TEXT`, `LIMIT_TEXT_*`, `GUARD_TEXT`, `ENDED_TEXT`) matching spec.md.

## Evidence
- commit `44e4c3b` (rdT17, task/rdT17) — `tools/supervisor.py` `window_missing`, `load_duo`, `_choose_windows`, `LIMIT_TEXT_SOLO`, `NO_WINDOW_TEXT`, `--partner` in `_start`; tests in `tests/test_supervisor_duo.py` (both windows -> duo, one window -> one solo child per profile with the right partner, none -> start failure, solo crash limit / guard, `window_missing` never places).
- commit `c5aec51` (rdT07) — `tools/supervisor.py` `running_supervisor` and the `return 2` refusal in `main`.
- `tools/supervisor.py` — `CHILDREN`, exit-code constants, text constants, `Supervisor._exited` / `_stop_both` / `run`, `_log_path` collision suffix, `_write_mode`.
- `tools/gear_loop.py` — exit 0/3/crash contract the supervisor relies on (see [gear-loop](gear-loop.md)).
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `tools/supervisor.py` `CHILDREN` (duo = gpg inviter + gpg2 joiner, both gear) and `_log_path` (profile-named logs); tests/test_supervisor_duo.py asserts the children.
- rdf04-t9 diff (the supervisor duo test file added on the task branch) — fake-child tests for per-bot crash counts, stop-both, files at exit.
