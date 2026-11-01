---
title: gear_loop roles, exit codes and records
type: component
updated: 2026-11-01
sources: [rdf04-t8, rdf04-i1]
---
# gear_loop roles, exit codes and records

`tools/gear_loop.py` runs one round loop per bot: `--role public` (gear-only, today's public room), `inviter` (LD gear bot, invites the partner) or `joiner` (GPG support bot, accepts the host's invite). `main(argv=None)` returns an exit code; `__main__` is `sys.exit(main())`; importing the module has no side effects.

## CLI and start
- `--profile {ld,gpg}` (default gpg), `--role {public,inviter,joiner}` (default public), `--execute`. Without `--execute` the injector is `make_injector(cfg, execute=False)` (dry run); `cfg = os.path.join(ROOT, prof.config)` also feeds `LiveGrabber`.
- config/duo.toml (new): `host` (inviter's game name, joiner accepts only it), `partner` (joiner's name, inviter invites it), `invite_wait_s` (300).
- Order in `main`: `discord.set_tag(prof.tag)` -> `capture.preflight.check([own])` (the inviter checks `['ld','gpg']` for window overlap) -> on failure status `⛔ 시작 점검 실패: <reason>` and return 3, before any injector exists -> `gear_bot.SUPPORT_SCALES = LD_SUPPORT_SCALES` for ld -> `▶ 봇 시작`. A clean exit sends the tagged `■ 봇 종료`.

## Exit codes (supervisor contract)
`EXIT_CLEAN = 0` (STOP seen between games), `EXIT_GUARD = 3` (window moved, 3 failed rounds in a row, wrong deck, start check failed), anything else is a crash (an exception propagates, never turned into 0 or 3). Each guard sends its status (per-role text in `FAIL_TEXT`, `WRONG_DECK_TEXT`) before returning.
- `data/STOP` is **never deleted** by gear_loop: two bots read it and the supervisor/Discord bot owns it (an earlier version removed it and would have hidden it from the second bot). `round_start` also honours STOP after a PAUSE wait.

## Round structure
`run_loop` -> `round_start` (STOP/PAUSE/moved) -> `leave_result_screen` -> `recover_step(f, g, inj, prof)` -> `lobby_phase(role)` -> `battle_phase`.
- `recover_step` returns `(frame, gave_up)`; `gave_up` (game cannot be relaunched after 2 launches, or 3 BACK/modal taps found no known screen) counts as a **failed round for every role**.
- Joiner: the round-start `recover_step` is skipped (it could close the host's invite popup with the modal X). Inside `coop_join.wait_and_accept` the callback `_joiner_recover` returns `gave_up`; a truthy value ends the wait as `'failed'` (this small change is in `coop_join.py`: `recover(f)` truthy -> `"recover gave up -- failed"`). Without it a game that never relaunches would loop on relaunches forever instead of reaching EXIT_GUARD.
- `recover_step(f, g, inj, prof, stop_on=None)`: `stop_on(frame)` truthy ends the loop at once with `(frame, False)`, checked at the top of every iteration, after each grab in the 120 s relaunch wait and after the unknown-screen wait, always before any tap or BACK. `_joiner_recover` passes `stop_on` = `invite.invite_popup(frame) is not None or should_stop() is not None` (STOP/PAUSE). Why: `wait_and_accept` checks the invite popup and STOP/PAUSE only between `recover` calls, but one `recover_step` call grabs up to 30 frames and taps MODAL_X/BACK, which would close an incoming invite (shop popup over the lobby while an invite arrives). A stop is not a give-up, so the wait goes on and handles the popup.
- `lobby_phase`: public -> `open_room_and_wait` (False = nobody joined, wait again, not a fail); inviter -> `friend_coop.invite_and_start(g, inj, partner, invite_wait_s, should_stop, uv=...)`; joiner -> `wait_and_accept(host, should_stop, recover=...)`.
- `battle_phase`: wait up to 90 s for battle, tap 배속 **once** (every role; skipped when the round resumed an already running battle), `run_battle(expect=prof.bot)`; duo roles pass a `support_play` wrapper that sets the `duo` flag. `wrong_deck` -> status + screenshot, no record, no 로비로 가기, exit 3.

## Records
Gear profile -> `data/gear_rounds.jsonl`, support profile -> `data/joiner_rounds.jsonl`; each line has `bot` and `mode` (`duo` for inviter/joiner, `gear` for public) plus the old fields. `room.json` is written only by the public role.

## Discord tag
`rdom.notify.discord.set_tag(tag)`; `send_status` inserts the tag after the leading emoji (`▶ 봇 시작` -> `▶ [기어] 봇 시작`), emoji stays first so the colour lookup is unchanged.

## Tests
`tests/test_gear_loop_roles.py` (fakes, tmp data dirs) covers each exit code, STOP file kept, joiner/inviter call restrictions, 배속 once, record paths, tag insertion, and a joiner whose game cannot be relaunched ending in EXIT_GUARD after 3 rounds with bounded `launch_game` calls. `tests/test_gear_loop_result.py` keeps the import-safe check. Never run the live loop in QA.

## Evidence
- commit `215efdc` — gear_loop roles, profiles, exit codes, per-bot records, tagged status, config/duo.toml, `set_tag`.
- commit `f9009fc` — `recover_step` returns `(frame, gave_up)`, joiner give-up ends `wait_and_accept` as failed, joiner skips round-start recover, config path under ROOT.
- commit `3827a9b` (rdf04-i1) — `stop_on` in `recover_step` / `_joiner_recover`; three tests in the gear_loop roles test file (not in this checkout until merge) (invite popup, STOP file, invite during the unknown wait: no BACK, no tap).
- `tools/gear_loop.py` — current main-checkout copy (pre-t8 until merge); tests/test_gear_loop_roles.py and config/duo.toml are added by the same commits on branch task/rdf04-t8 (not in this checkout until merge, so not lint-checked).
- [coop-join](coop-join.md), [coop-invite](coop-invite.md), [preflight](preflight.md), [support-bot-core](support-bot-core.md) — the pieces it wires.
