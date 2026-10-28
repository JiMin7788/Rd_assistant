---
title: Run the bot (launchers, dry-run, live)
type: howto
updated: 2026-10-29
sources: [seed, rdf01-t12, rdf01-t13]
---
# Run the bot (launchers, dry-run, live)

Production = `봇 시작.bat` → `tools/run_all.py` (Discord bot + supervisor → `tools/gear_loop.py`).
Everything else is a manual / dry-run entry point. Run from `C:\dev\rdom` with `.venv`.

## Production (gear deck, coop rooms)
- Start: `봇 시작.bat` = `.venv\Scripts\python.exe -u tools\run_all.py %*` (`--no-game` = Discord only;
  start the game loop later with Discord `/시작`). One console; closing it stops both.
- Pause after current game: `봇 일시정지.bat` (creates `data\PAUSE`); resume: `봇 재개.bat` (deletes it).
- Clean stop: Discord `/종료` (writes `data\STOP`).
- Logs: `data/bot_logs/YYYYMMDD_HHMM.log`, `data/bot_logs/supervisor.log`, `data/discord_bot.log`;
  per-round results `data/gear_rounds.jsonl`.
- Each round goes through `support_bot.run_battle`, so the loop plays either the gear or the support deck
  ([support-bot-core](../components/support-bot-core.md)). `config/deck.toml` `force = "support"` forces the support
  player (H1 data collection); the manual steps are in `CLAUDE_CODE_TODO.md` ("rdF01 서포팅덱").
- Needs `config/discord.toml` (gitignored, holds the bot token / webhooks — never commit or print it).

## Gear bot on the current battle
- Dry-run: `python tools/gear_bot.py` (prints actions). Real: `python tools/gear_bot.py --execute [--tick 0.6] [--minutes 30]`.

## Predator-deck bot (older path)
- One grab, dry-run: `python tools/bot_live.py`; loop: `--loop 20`; real input: `--loop 20 --execute`.
- Other modes: `--summon-spam`, `--play-battle`, `--autoplay`, `--start-coop`, `--start-friend NAME`, `--collect`.
- User-started battles: `python tools/play.py [rounds]` (injects for real).
- Offline frame check: `python tools/bot_dryrun.py <frame.png>` (read → evaluate → plan, no input).

## Support deck offline check
- `python tools/support_dryrun.py <frame.png>` prints 6 lines: three board rows of five `#<cell> <Type> <pip>`,
  `evaluate: {...}`, `planned action: {...}` (planned with `support_ready=True`, so the supporter branch shows),
  `score: <N|None>`. No game, no input; the module does not import `rdom.input.inject`.
- Without support models in the data dir all 15 cells read `junk 0`, the plan is `op: wait` and score is `None`
  (the test points `perception.support._DATA` at an empty tmp dir and resets `_models`).
- `dryrun(frame_rgb)` is pure and returns the lines; `main(argv)` loads the PNG via PIL (RGB) and returns 0, or 2 on bad usage.

## Evidence
- `봇 시작.bat`, `봇 일시정지.bat`, `봇 재개.bat` — exact commands
- `tools/run_all.py` — docstring, `--no-game`, log paths
- `tools/supervisor.py`, `tools/gear_loop.py` — loop, PAUSE/STOP, `data/gear_rounds.jsonl`
- `tools/discord_bot.py` — slash commands, token from `config/discord.toml`
- `tools/gear_bot.py`, `tools/bot_live.py`, `tools/play.py`, `tools/bot_dryrun.py` — argparse/usage
- `.gitignore` — `config/discord.toml`
- `tools/gear_loop.py`, `config/deck.toml`, `CLAUDE_CODE_TODO.md` — run_battle call, `force` comment, H1-H3 runbook (commit `e3cf60a`)
- commit `4aa774e` — adds tools/support_dryrun.py (dryrun/main, output lines, support_ready=True, imports) and tests/test_support_dryrun.py (empty-data-dir expectations junk 0 / wait / score None, no-inject check); not yet merged into the main checkout
