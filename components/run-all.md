---
title: run_all console (duo / gear-only, tagged tails)
type: component
updated: 2026-11-05
sources: [rdf04-t10, rdf04-i1, rdT06]
---
# run_all console (duo / gear-only, tagged tails)

`tools/run_all.py` starts the Discord bot and the supervisor (default `--mode duo`, `--gear-only` = `--mode gear`) and echoes the important lines of three logs tagged `[기어1]` / `[기어2]` / `[디코]` (rdT06: both duo bots are gear bots on two Google Play Games windows).

## Flags and header
- `--no-game`: Discord bot only (unchanged). `--gear-only`: supervisor gets `--mode gear`; default gets `--mode duo`. The mode is always passed explicitly (`supervisor_args`), even though the supervisor defaults to duo too.
- Header printed after the supervisor starts: `두 봇 시작 (기어1=구글 <host> · 기어2=구글 <partner>)` or `기어봇만 시작 (구글)` (`header_text`). Names come from `config/duo.toml` keys `host` / `partner` (`load_names`); a missing file or key falls back to `대변먹는자` / `배속봇`.
- **Single instance (rdT07):** if `data/run_all.pid` names another live python process, `main` prints `이미 실행 중이에요 -- 두 번째 실행은 무시합니다 (pid N)...`, waits `SECOND_COPY_WAIT_S` (5 s) and returns 1 without starting a bot or touching the lock. (2026-11-05 two full stacks ran at once and every window had two bots tapping.) Discord `/시작` already refuses when `supervisor.pid` is alive ("이미 실행 중입니다."), and the supervisor itself now refuses too.
- If `data/supervisor.pid` is alive the supervisor is left alone ("게임봇은 이미 실행 중"), so the flags then have no effect. `PAUSE` / `STOP` are removed before a fresh start, as before.

## Tails and SHOW
- `tail_specs`: `data/bot_logs/2*_gpg[_.]*` -> `[기어1]`, `data/bot_logs/2*_gpg2*` -> `[기어2]` (logs are named by profile; `gpg[_.]*` does not match gpg2 files and does match a same-minute restart `YYYYMMDD_HHMM_gpg_2.log` from `supervisor._log_path`; without it the console stayed on the old file and hid the restarted bot), `data/discord_bot.log` -> `[디코]`. One `Tail` per pattern so each bot follows its own newest log (the old shared `2*.log` pattern is gone). `supervisor.log` is not followed (`tag_for` returns None).
- `SHOW` additionally matches `invite`, `초대`, `start check`, `시작 점검`, `wrong deck`, `restart`; `shown(line)` is the substring test.

## Import is side-effect free
Lock file, child processes and the tail loop live in `main(argv)`; importing the module (tests do, via `importlib`) starts nothing. Tests are in the rdf04-t10 duo test file.

## Evidence
- `tools/run_all.py` — `supervisor_args`, `header_text`, `load_names`, `tail_specs`, `tag_for`, `shown`, `SHOW`, `main`.
- rdf04-t10 diff (the run_all duo test file added on the task branch) — args, header texts, default names, tags/patterns, SHOW keys, import starts no process.
- `tools/supervisor.py` — the `--mode` values and log names it produces (see [supervisor](supervisor.md)).
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `tools/run_all.py` `tail_specs` (gpg / gpg2 patterns) and `header_text`.
- commit `28b4fce` (task/rdf04-t10) — the change.
- commit `3827a9b` (rdf04-i1) — `*_gear*.log` / `*_support*.log` patterns; the run_all duo test file checks `_2` names in `tag_for` and the new patterns.
