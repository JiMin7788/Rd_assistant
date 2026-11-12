---
title: Discord bot (duo / gear texts, /시작 대상)
type: component
updated: 2026-11-12
sources: [rdf04-t11, rdT06, rdT15, rdT17]
---
# Discord bot (duo / gear texts, /시작 대상)

`tools/discord_bot.py` is mode-aware: it asks `duo_texts.mode_now()` (duo | solo | gear | off) and every user-facing text, the room-code card, presence, `/스샷` and `/로그` switch on that mode. All the texts and small pure helpers live in `src/rdom/notify/duo_texts.py`, which is import-safe and has no Discord dependency.

## Mode
- `mode_now()` in the bot is `duo_texts.mode_now(DATA, running())`. It reads `data/bot_mode.json` (written by the supervisor, see [supervisor](supervisor.md)) and returns `off` when the supervisor is not alive or the file is missing, unreadable or holds another value.
- Gear-only texts are the production texts from before duo mode; only the duo variants are new.
- **Solo (rdT17, "한 창 모드"):** `mode_now` also returns `solo` (the supervisor found one game window; that bot invites the other account). `solo_now()` = `duo_texts.solo_now(DATA)` gives `{profile, name, partner}` from `bot_mode.json`. Solo behaves like duo for the queue (reservations / `/방코드` blocked with `SOLO_BLOCK` `지금은 봇이 친구를 초대해서 플레이 중이라 참가할 수 없어요`, `tick()` only sets the `solo` card `🤖 봇이 친구를 초대해서 플레이 중`). `/상태` title `status_title(mode, paused, stopping, solo_now())` = `🟢 실행 중 · 🤖 한 창 모드 (서폿=구글 배속봇, 대변먹는자 초대)` (label 기어1 for gpg, 서폿 for gpg2); room line = the solo card title; presence `랜다2 한 창 모드 · 오늘 N판`; `/로그` and the `/상태` log use `mode_logs(mode)` = only the running bot's newest log; `/스샷` `screens_for(mode, solo)` captures only the open window; `/정지` / `/종료` use the single-bot wording. `/시작 둘 다` stays `--mode duo`; the supervisor decides solo. Duo texts are unchanged.

## Behaviour by command
- `/시작 [대상]`: choices `둘 다` (value `duo`, the default) and `기어만` (`gear`). Starts `tools/supervisor.py --mode <target>`; replies with `start_reply(target)`. If the supervisor already runs it still answers "이미 실행 중입니다." and does not switch mode.
- `/예약`: in duo it answers `DUO_BLOCK` (ephemeral) before touching the queue, so nobody is added.
- `/방코드`: `code_reply(mode, room, queue_busy)`; duo gives `DUO_BLOCK`.
- `tick()`: in duo it only calls `set_card("duo")` and returns, so the queue is untouched (no pops, DMs or timeouts). The duo card is a purple embed built from `card_for`.
- `/정지` and `/종료` use `pause_reply` / `stop_reply` ("두 봇 모두" in duo).
- `/상태`: title from `status_title(mode, paused, stopping)`, room line from `room_line`; in duo the log section is `log_blocks(duo_logs(), 6, 1800)`.
- `/로그`: in duo one message with a header and code block per bot, lines clamped to 1..60; budget `limit // n_tags` per tag, whole message cut to 1900 chars.
- `/스샷`: `screens_for(mode)`. Duo sends two files (`[기어1]` from `config/recorder.toml` as `gear.jpg`, `[서폿]` from `config/recorder_gpg2.toml` as `support.jpg`; gpg2 is the support joiner since rdT15) with content `SHOT_CONTENT`. Gear-only and off send the first GPG window as `screen.jpg`. Since rdT06 the duo texts name the two Google windows (`기어1=구글 대변먹는자 · 서폿=구글 배속봇`, rdT15), no LD; the `duo_logs()` tag for the `*_gpg2*` log is `[서폿]`. `screencap(config)` takes the recorder config path.
- Presence: duo "랜다2 봇 두 대 · 오늘 N판", gear "랜다2 협동 · 오늘 N판 · 대기 N명", off "꺼짐" with status idle; a PAUSE file overrides with idle "일시정지".

## Pitfalls
- `duo_logs()` picks the newest file per bot with the globs `*_gpg[_.]*` and `*_gpg2*` (logs are named by profile) in `data/bot_logs/`, matching the supervisor's per-bot log names. A missing log gives the text `(로그 없음)` for that tag.
- `data/bot_mode.json` alone is not trusted: a stale file with a dead supervisor reads as `off`.
- The commit rewrote `tools/discord_bot.py` with a whole-file line-ending change (about 1086 changed lines in `git diff --stat`); the real change is about 150 lines. Use `git diff -w --ignore-cr-at-eol` to review it.
- Tests: `tests/test_duo_texts.py` covers the pure helpers; the Discord wiring itself has no automated test.

## Evidence
- commit `44e4c3b` (rdT17, task/rdT17) — `src/rdom/notify/duo_texts.py` `SOLO_BLOCK`, `SOLO_TITLE`, `solo_now`, `solo_start_text`, `solo_status`, solo branches of `mode_now` / `reserve_blocked` / `code_reply` / `card_for` / `status_title` / `room_line` / `presence` / `screens_for`; `tools/discord_bot.py` `solo_now`, `mode_logs`, tick / set_card / status_embed / cmd_log / cmd_shot; `tests/test_duo_texts.py` `test_solo_mode_and_details`, `test_solo_texts` and the source checks.
- `tools/discord_bot.py` — mode_now/duo_logs, tick duo early-return, cmd_start choices and `--mode`, cmd_reserve block, cmd_shot, cmd_log, status_embed, presence_loop.
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `src/rdom/notify/duo_texts.py` (`DUO_STATUS`, `START_REPLY`, `screens_for`) and `tools/discord_bot.py` `duo_logs`.
- commit `62b1d25` — rdf04-t11 change. It adds src/rdom/notify/duo_texts.py (mode_now, texts, card_for, log_blocks, screens_for, presence) and tests/test_duo_texts.py (helper unit tests); the line-ending note comes from its diffstat.
