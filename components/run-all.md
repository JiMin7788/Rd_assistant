---
title: run_all console (duo / gear-only, tagged tails)
type: component
updated: 2026-11-01
sources: [rdf04-t10]
---
# run_all console (duo / gear-only, tagged tails)

`tools/run_all.py` starts the Discord bot and the supervisor (default `--mode duo`, `--gear-only` = `--mode gear`) and echoes the important lines of three logs tagged `[기어]` / `[서폿]` / `[디코]`.

## Flags and header
- `--no-game`: Discord bot only (unchanged). `--gear-only`: supervisor gets `--mode gear`; default gets `--mode duo`. The mode is always passed explicitly (`supervisor_args`), even though the supervisor defaults to duo too.
- Header printed after the supervisor starts: `두 봇 시작 (기어=LD <host> · 서폿=구글 <partner>)` or `기어봇만 시작 (LD)` (`header_text`). Names come from `config/duo.toml` keys `host` / `partner` (`load_names`); a missing file or key falls back to `대변먹는자` / `배속봇`.
- If `data/supervisor.pid` is alive the supervisor is left alone ("게임봇은 이미 실행 중"), so the flags then have no effect. `PAUSE` / `STOP` are removed before a fresh start, as before.

## Tails and SHOW
- `tail_specs`: `data/bot_logs/2*_gear.log` -> `[기어]`, `data/bot_logs/2*_support.log` -> `[서폿]`, `data/discord_bot.log` -> `[디코]`. One `Tail` per pattern so each bot follows its own newest log (the old shared `2*.log` pattern is gone). `supervisor.log` is not followed (`tag_for` returns None).
- `SHOW` additionally matches `invite`, `초대`, `start check`, `시작 점검`, `wrong deck`, `restart`; `shown(line)` is the substring test.

## Import is side-effect free
Lock file, child processes and the tail loop live in `main(argv)`; importing the module (tests do, via `importlib`) starts nothing. Tests are in the rdf04-t10 duo test file.

## Evidence
- `tools/run_all.py` — `supervisor_args`, `header_text`, `load_names`, `tail_specs`, `tag_for`, `shown`, `SHOW`, `main`.
- rdf04-t10 diff (the run_all duo test file added on the task branch) — args, header texts, default names, tags/patterns, SHOW keys, import starts no process.
- `tools/supervisor.py` — the `--mode` values and log names it produces (see [supervisor](supervisor.md)).
- commit `28b4fce` (task/rdf04-t10) — the change.
