---
title: Run the bot (launchers, dry-run, live)
type: howto
updated: 2026-11-01
sources: [seed, rdf01-t12, rdf01-t13, rdf02-t7, rdf02-m1, rdf03-t8, rdf03-t10, rdf03-m2, rdf04-t2, rdf04-t9, rdf04-t10, rdf04-t12]
---
# Run the bot (launchers, dry-run, live)

Production = `봇 시작.bat` → `tools/run_all.py` (Discord bot + supervisor → `tools/gear_loop.py`).
Everything else is a manual / dry-run entry point. Run from `C:\dev\rdom` with `.venv`.

## Production (gear deck, coop rooms)
- Start: `봇 시작.bat` = `.venv\Scripts\python.exe -u tools\run_all.py %*` (`--no-game` = Discord only;
  start the game loop later with Discord `/시작`; `--gear-only` = gear bot alone on LD, default = duo). One
  console; closing it stops everything. Console tags and SHOW lines: [run-all](../components/run-all.md).
- Pause after current game: `봇 일시정지.bat` (creates `data\PAUSE`); resume: `봇 재개.bat` (deletes it).
- Clean stop: Discord `/종료` (writes `data\STOP`).
- Supervisor modes, per-bot restart and stop-both: [supervisor](../components/supervisor.md).
- Logs: `data/bot_logs/YYYYMMDD_HHMM_<bot>.log` (supervisor children), `data/bot_logs/supervisor.log`, `data/discord_bot.log`;
  per-round results `data/gear_rounds.jsonl`.
- Each round goes through `support_bot.run_battle`, so the loop plays either the gear or the support deck
  ([support-bot-core](../components/support-bot-core.md)). `config/deck.toml` `force = "support"` forces the support
  player (H1 data collection); the manual steps are in `CLAUDE_CODE_TODO.md` ("rdF01 서포팅덱").
- `run_all.py` echoes only log lines containing a `SHOW` substring; since rdf02-t7 that includes `unreadable`
  and `board changed without our action` (cell-memory lines). The `burst cells` line is not echoed: read it in
  `data/bot_logs/<date>.log`.
- H2 trial-mode runbook (in `CLAUDE_CODE_TODO.md`, starts only after rdF02 is merged): clear `force`, play 3+
  trial games, watch five console lines (`deck route: support (deck bar)`, `support deck: trial mode ...`,
  `power panel -> ...`, `cell ... unreadable`, `board changed without our action`); after each game check
  `bursts` / `burst_hits` / `forgets` in the last line of `data/support_rounds.jsonl` (many bursts but few hits
  -> tell the Master); keep `panel_*.png` and `data/crops_support/_burst/`. The H2 section now says in Korean
  that H1 and the rdF02 calibration (score, deck bar, power cards, LV_BOX) are done and H2 starts after rdF02
  is merged. H1 is marked done there (type gate PASS, pip gate FAIL).
- H3 acceptance runbook (R14, in `CLAUDE_CODE_TODO.md` "H3 — 인수", Korean; H2 is marked done there: 3 trial
  games, type and pip gates PASS after rdT04): confirm both gates PASS (`support deck: play mode`), `force = ""`,
  play 5+ play-mode normal coop games, then `python tools/support_judge.py` and the user re-checks the
  screenshots. Pass = m1/m2/m3 in 4 of the last 5 eligible games (clear/game_over); a fail with matching
  screenshots goes back to the user for new rules, the criterion is not relaxed. Since rdf03-t10 `SHOW` also
  echoes `power-up`, `Lv check`, `look-alike`, `game-over screen`, `support result`, `battle still on screen`
  (the runbook also lists `support deck: play mode`, `power panel ->`, `tap not confirmed`, already shown via
  `support deck` / `power panel`). After each game read the last `data/support_rounds.jsonl` line: `result`,
  `final_score`, `max_score`, `power.bought`, `power.unconfirmed`, `power.lv_check`; report to the Master if
  `power.bought` stays 0, `unconfirmed` is high, an `lv_check` mismatch appears, or a look-alike/once frame was
  saved (`data/support_runs/<game_id>/gameover_*.png`). Keep `panel_*.png` and `gameover_*.png` (runbook line, rdf03-m2).
- H4 two-bot acceptance runbook (rdF04, in `CLAUDE_CODE_TODO.md` "H4 — 두 봇 인수", Korean). Pass = one coop
  game played to the end by both bots with no guard stop and no crash ("한 판만 되면 됨"). Steps: (1)
  `python tools/duo_check.py`, every `start check:` line OK; (2) LD dry-run while the user plays one gear game:
  `gear_bot.py --profile ld` plus `save_frame.py --profile ld --every 5 --minutes 20`, then the Master runs
  `check_ld_profile.py <folder>` and mismatches are fixed before step 3; (3) live duo game with the user watching
  (`봇 시작.bat`): invite -> accept -> start -> both bots at 2.0x -> game over -> both back in lobby -> second invite;
  watch the support bot's `power-up` / `power panel ->` lines at 2.0x (SP and power timing were measured at 1.5x);
  (4) Discord `/종료` must show `■ 봇 종료` for [기어] and [서폿]; `■ 두 봇 모두 정지됨` or `⛔` means guard/crash = fail.
  On failure send `data/bot_logs/*_gear.log`, `*_support.log` and the Discord screenshots. Open items listed there:
  LD support-deck detection unverified on a real LD screen, and the rdf04-t1 `check_ld_profile` items.
  `test_h4_runbook_commands_exist_in_code` (tests/test_save_frame_tool.py) fails if a tool or flag named in the
  H4 section stops existing. `docs/01_GAME_SPEC.md` emulator section now states both emulators run together
  (GPG = support bot / PostMessage, LD = gear bot / adb).
- `python tools/support_dryrun.py --help` (or `-h`) prints the usage line and exits 0; `python
  tools/build_digit_templates.py --help` prints argparse usage. Before, `--help` was taken as a kind name and
  wrote `assets/templates/digits_--help.npz`.
- Needs `config/discord.toml` (gitignored, holds the bot token / webhooks — never commit or print it).

## Gear bot on the current battle
- Dry-run: `python tools/gear_bot.py` (prints actions). Real: `python tools/gear_bot.py --execute [--tick 0.6] [--minutes 30]`.

- `--profile {ld,gpg}` (default gpg) picks `config/recorder_ld.toml` / `config/recorder.toml` for both the
  `LiveGrabber` and `make_injector`; `python tools/gear_bot.py --profile ld` is the LDPlayer dry-run (adb input
  only with `--execute`).
- `python tools/save_frame.py --profile ld` saves one frame; `--every SEC --minutes MIN` (both required) saves a
  frame every SEC s into `data/support_frames/manual/<profile>_<stamp>/`, skips obscured grabs, never overwrites,
  and exits 1 when nothing was saved. Reads the screen only.

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
- `python tools/support_dryrun.py --data-dir <dir> <frame.png>` points both `support._DATA` and `gear._DATA` at `<dir>` (the support nets and the gear pip fallback both read `gear._DATA`) and clears the cached nets; use it in a worktree, where `<repo>/data` is empty. `--data-dir` is only accepted as the first of three args; `--data-dir x` alone or any other arg count prints the usage line and returns 2.
- `dryrun(frame_rgb)` is pure and returns the lines; `main(argv)` loads the PNG via PIL (RGB) and returns 0, or 2 on bad usage.

## Evidence
- `CLAUDE_CODE_TODO.md` — H3 runbook keep line now keeps the panel and gameover frames (commit `786b5a7`, task/rdf03-m2)
- `봇 시작.bat`, `봇 일시정지.bat`, `봇 재개.bat` — exact commands
- `tools/run_all.py` — docstring, `--no-game`, log paths
- `tools/supervisor.py`, `tools/gear_loop.py` — loop, PAUSE/STOP, `data/gear_rounds.jsonl`
- `tools/discord_bot.py` — slash commands, token from `config/discord.toml`
- `tools/gear_bot.py`, `tools/bot_live.py`, `tools/play.py`, `tools/bot_dryrun.py` — argparse/usage
- `.gitignore` — `config/discord.toml`
- `tools/gear_loop.py`, `config/deck.toml`, `CLAUDE_CODE_TODO.md` — run_battle call, `force` comment, H1-H3 runbook (commit `e3cf60a`)
- `tools/run_all.py` (`SHOW` tuple), `CLAUDE_CODE_TODO.md` (H1 done / H2 runbook) — commit `d4aff7c` (not yet merged into the main checkout; also adds test_save_frame_tool.py)
- commit `2e74942` (branch task/rdf02-m1) — H2 wording in CLAUDE_CODE_TODO.md; `--help` handling in tools/support_dryrun.py and tools/build_digit_templates.py; tests `test_dryrun_help_subprocess_exit_0`, `test_build_digit_templates_help_writes_nothing` in tests/test_support_m1_inputs.py
- commit `04c74c9` (branch task/rdf03-t8) — tools/support_dryrun.py `--data-dir` and `USAGE`; tests `test_usage_text_and_exit_codes`, `test_data_dir_sets_model_dirs` in tests/test_support_dryrun.py
- commit `557bf89` (branch task/rdf03-t10) — `CLAUDE_CODE_TODO.md` H2 done / H3 R14 runbook; `tools/run_all.py` `SHOW` additions; tests `test_run_all_show_has_play_mode_lines`, `test_h3_runbook_lines_exist_in_code` in tests/test_save_frame_tool.py
- `CLAUDE_CODE_TODO.md` ("### H4"), `docs/01_GAME_SPEC.md` (rdF04 emulator line), `tests/test_save_frame_tool.py` (`test_h4_runbook_commands_exist_in_code`) — task rdf04-t12, commit `b7efbf8`
- `tools/gear_bot.py`, `tools/save_frame.py` (`PROFILES`, `run_every`, `main`) — commit `3635c90` (rdf04-t2), which also adds the `save_frame --every` test
- commit `4aa774e` — adds tools/support_dryrun.py (dryrun/main, output lines, support_ready=True, imports) and tests/test_support_dryrun.py (empty-data-dir expectations junk 0 / wait / score None, no-inject check); not yet merged into the main checkout
