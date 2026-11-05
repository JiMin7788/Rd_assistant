---
title: gear_loop roles, exit codes and records
type: component
updated: 2026-11-06
sources: [rdf04-t8, rdf04-i1, rdT06, rdT07, rdT10, rdT11, rdT12, rdT14]
---
# gear_loop roles, exit codes and records

`tools/gear_loop.py` runs one round loop per bot: `--role public` (gear-only, today's public room), `inviter` (gear bot on profile `gpg`, invites the partner) or `joiner` (gear bot on profile `gpg2`, accepts the host's invite; since rdT06 both duo bots are gear). `main(argv=None)` returns an exit code; `__main__` is `sys.exit(main())`; importing the module has no side effects.

## CLI and start
- `--profile {ld,gpg,gpg2}` (default gpg), `--role {public,inviter,joiner}` (default public), `--execute`. Without `--execute` the injector is `make_injector(cfg, execute=False)` (dry run); `cfg = os.path.join(ROOT, prof.config)` also feeds `LiveGrabber`.
- config/duo.toml (new): `host` (inviter's game name, joiner accepts only it), `partner` (joiner's name, inviter invites it), `invite_wait_s` (300).
- Order in `main`: `discord.set_tag(prof.tag)` -> `capture.preflight.check([own])` (the inviter checks `['gpg','gpg2']` for window overlap) -> on failure status `⛔ 시작 점검 실패: <reason>` and return 3, before any injector exists -> `gear_bot.SUPPORT_SCALES = LD_SUPPORT_SCALES` for ld -> `▶ 봇 시작`. A clean exit sends the tagged `■ 봇 종료`.

## Exit codes (supervisor contract)
`EXIT_CLEAN = 0` (STOP seen between games), `EXIT_GUARD = 3` (window moved, 3 failed rounds in a row, wrong deck, start check failed), anything else is a crash (an exception propagates, never turned into 0 or 3). Each guard sends its status (per-role text in `FAIL_TEXT`, `WRONG_DECK_TEXT`) before returning.
- `data/STOP` is **never deleted** by gear_loop: two bots read it and the supervisor/Discord bot owns it (an earlier version removed it and would have hidden it from the second bot). `round_start` also honours STOP after a PAUSE wait.

## Round structure
`run_loop` -> `round_start` (STOP/PAUSE/moved) -> `leave_result_screen` -> `recover_step(f, g, inj, prof)` -> `lobby_phase(role)` -> `battle_phase`.
- `recover_step` returns `(frame, gave_up)`; `gave_up` (game cannot be relaunched after 2 launches, or 3 BACK/modal taps found no known screen) counts as a **failed round for every role**.
- Joiner: the round-start `recover_step` is skipped (it could close the host's invite popup with the modal X). Inside `coop_join.wait_and_accept` the callback `_joiner_recover` returns `gave_up`; a truthy value ends the wait as `'failed'` (this small change is in `coop_join.py`: `recover(f)` truthy -> `"recover gave up -- failed"`). Without it a game that never relaunches would loop on relaunches forever instead of reaching EXIT_GUARD.
- `recover_step(f, g, inj, prof, stop_on=None)`: `stop_on(frame)` truthy ends the loop at once with `(frame, False)`, checked at the top of every iteration, after each grab in the 120 s relaunch wait and after the unknown-screen wait, always before any tap or BACK. `_joiner_recover` passes `stop_on` = `invite.invite_popup(frame) is not None or should_stop() is not None` (STOP/PAUSE). Why: `wait_and_accept` checks the invite popup and STOP/PAUSE only between `recover` calls, but one `recover_step` call grabs up to 30 frames and taps MODAL_X/BACK, which would close an incoming invite (shop popup over the lobby while an invite arrives). A stop is not a give-up, so the wait goes on and handles the popup.
- `lobby_phase`: public -> `open_room_and_wait` (False = nobody joined, wait again, not a fail); inviter -> `friend_coop.invite_and_start(g, inj, partner, invite_wait_s, should_stop, uv=...)`; joiner -> `wait_and_accept(host, should_stop, recover=...)`.
- Unknown-screen wait (rdT11): `recover_step(..., unknown_wait_s=UNKNOWN_WAIT_S)` waits 5 s before the BACK; `_joiner_recover` passes `JOINER_UNKNOWN_WAIT_S` = 15 s so the joiner's room -> battle loading screen is never BACKed (2026-11-05: two BACKs right before its battle).
- `battle_phase`: wait up to 90 s for battle, `confirm_speed` (rdT07; rdT12 removed the rdT11 `tap_allowed` inviter exception): both duo bots (and public) use 배속, also on a resumed battle (user 2026-11-05: '아 둘 다 배속 사용'). rdT14 rule (user 2026-11-05 23:5x '배속 둘 다 눌러서 2.0 만들어야한다고 대변먹는자가 안누르잖아'; the 23:14 run with the rdT12 stop-on-own-rise rule ended at 1.5 for the inviter, game mechanics unknown): every bot keeps tapping until the shared speed reads 2.0. The loop: read the caption with `read_speed`; if >= 2.0 stop; else tap 배속 (`SPEED_UV`), wait `SPEED_RETAP_S` = 1.5 s, re-read. A rise caused by us does not stop it; only 2.0, `SPEED_TAPS_MAX` = 5 taps or `SPEED_WINDOW_S` = 20 s ends it. Summary log `배속 <before> -> <after>`. Per tap it logs `  배속 tap <n>/5: <reading before tap> -> <reading after> (front ok|NOT in front)` (`inj.last_gesture_ok`, default True for AdbInjector) and saves the frame before the first tap and the frame after each tap to `data/coop_debug/speed_<profile>_<YYYYmmdd_HHMMSS>_<n>.png` (`_save_speed_frame`, 0 = before the first tap, newest `SPEED_DEBUG_KEEP` = 30 `speed_*` files kept, tests patch `friend_coop.COOP_DEBUG_DIR`). A caption unreadable after a tap is re-read every 0.5 s for up to `SPEED_REREAD_S` = 3 s (rdT10; 2026-11-05 `1.0 -> None` ended the loop early); still unreadable ends the loop (a blind extra tap could cycle 2.0 -> 1.0). `battle_phase` also calls `log_input_stats(inj)` once per round: `input: N gestures, N switches, N not in front, N lock timeouts, waited N (avg X ms, max Y ms), start-to-post avg X ms, max Y ms` (rdT11 added the waited/start-to-post part, see [input-inject](input-inject.md)), then resets the counters. A round that resumed a running battle (`tap_speed` False) runs the same loop but only when the first reading is legible and below 2.0. Then `run_battle(expect=prof.bot)`; duo roles pass a `support_play` wrapper that sets the `duo` flag. `wrong_deck` -> status + screenshot, no record, no 로비로 가기, exit 3.

## 로비로 가기 retry (rdT07)
`after_battle`: when `exit_to_lobby` returns False it logs `로비로 가기 failed -- retrying once`, sleeps 3 s, re-checks that no battle is on screen (the "battle still on screen" guard stays) and runs `exit_to_lobby` once more; a second failure saves the frame via `friend_coop.save_debug_frame("lobby_fail", ...)` to `data/coop_debug/lobby_fail_<timestamp>.png` (newest 20 kept) and logs the path. Cause: 2026-11-05 CleanCardinal never left the result screen.

## Records
The file follows the **role** (rdT06): joiner -> `data/joiner_rounds.jsonl`, public / inviter -> `data/gear_rounds.jsonl` (`battle_phase`). It used to follow `prof.bot`, which would send both duo gear bots to one file; each line has `bot` and `mode` (`duo` for inviter/joiner, `gear` for public) plus the old fields. `room.json` is written only by the public role.

## Discord tag
`rdom.notify.discord.set_tag(tag)`; `send_status` inserts the tag after the leading emoji (`▶ 봇 시작` -> `▶ [기어] 봇 시작`), emoji stays first so the colour lookup is unchanged.

## Tests
`tests/test_gear_loop_roles.py` (fakes, tmp data dirs) covers each exit code, STOP file kept, joiner/inviter call restrictions, 배속 once, record paths, tag insertion, and a joiner whose game cannot be relaunched ending in EXIT_GUARD after 3 rounds with bounded `launch_game` calls. `tests/test_gear_loop_result.py` keeps the import-safe check. Never run the live loop in QA.

## Evidence
- commit `7d8f41a` (rdT14, task/rdT14) — `tools/gear_loop.py` `SPEED_TAPS_MAX` 5, `SPEED_WINDOW_S`, `SPEED_RETAP_S`, `SPEED_DEBUG_KEEP`, `_save_speed_frame`, `confirm_speed` (no stop on own rise, per-tap log line, AI-NOTE with the 23:14 run); `tests/test_gear_loop_roles.py` speed tests (tap log line, frames capped at 30 with patched `COOP_DEBUG_DIR`, 5-tap cap, 20 s window).
- `tools/gear_loop.py` (rdT11, task/rdT11) — `UNKNOWN_WAIT_S`, `JOINER_UNKNOWN_WAIT_S`, `recover_step(unknown_wait_s=)`, `confirm_speed`, `battle_phase` calls (rdT12 dropped `tap_allowed`), `log_input_stats`; tests in `tests/test_gear_loop_roles.py`.
- commit `9c8ce09` (rdT10) — `tools/gear_loop.py` `SPEED_REREAD_S`, `confirm_speed` re-read loop, `log_input_stats`; `tests/test_gear_loop_roles.py`.
- commit `c5aec51` (rdT07) — `tools/gear_loop.py` `confirm_speed`, `SPEED_TAPS_MAX`, `battle_phase` branches, `after_battle` retry; tests in `tests/test_gear_loop_roles.py`, `tests/test_gear_loop_result.py`.
- commit `215efdc` — gear_loop roles, profiles, exit codes, per-bot records, tagged status, config/duo.toml, `set_tag`.
- commit `f9009fc` — `recover_step` returns `(frame, gave_up)`, joiner give-up ends `wait_and_accept` as failed, joiner skips round-start recover, config path under ROOT.
- commit `3827a9b` (rdf04-i1) — `stop_on` in `recover_step` / `_joiner_recover`; three tests in the gear_loop roles test file (not in this checkout until merge) (invite popup, STOP file, invite during the unknown wait: no BACK, no tap).
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `tools/gear_loop.py` `battle_phase` (`log = JOINER_LOG if role == "joiner" else GEAR_LOG`), `main` (`names = ["gpg", "gpg2"]` for the inviter), `--profile` help.
- `tools/gear_loop.py` — current main-checkout copy (pre-t8 until merge); tests/test_gear_loop_roles.py and config/duo.toml are added by the same commits on branch task/rdf04-t8 (not in this checkout until merge, so not lint-checked).
- [coop-join](coop-join.md), [coop-invite](coop-invite.md), [preflight](preflight.md), [support-bot-core](support-bot-core.md) — the pieces it wires.
