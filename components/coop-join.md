---
title: Joiner flow (wait_and_accept)
type: component
updated: 2026-11-05
sources: [rdf04-t4, rdf04-t8, rdT05, rdT10, rdT11]
---
# Joiner flow (wait_and_accept)

`rdom.input.coop_join.wait_and_accept` is the support bot's lobby side of duo mode: wait for the host's 게임 초대 popup, check the inviter name, accept or decline, join the room and wait for the battle. One function for the loop to call; wired into `gear_loop` as the joiner role (see [gear-loop](gear-loop.md)).

## Contract
`wait_and_accept(g, inj, host, should_stop, recover, now, sleep, join_s=20, room_s=120)` returns `'battle' | 'failed' | 'stopped' | 'paused'`. `'room_timeout'` is in the task spec but is never returned: a room that outlives `room_s` is `'failed'` (the loop counts failed rounds). `should_stop()` returns None, `'stop'` or `'pause'`; `recover(f)` is the loop's popup/relaunch step, injected; a truthy return means the loop gave up (game will not start) and the wait ends `'failed'` (rdf04-t8).

## Order per frame (TICK_S 0.5 s, so should_stop is checked well inside 2 s)
1. `board.is_battle` -> `'battle'`.
2. `invite.invite_popup` FIRST, before `recover`: the lobby recovery taps the modal X, which would close the invite popup.
3. `invite.joined_room` -> in-room wait.
4. Otherwise `recover(f)` (only in the waiting phase) and a "still waiting for an invite (n min)" log every 60 s.

## Name check
Each popup frame calls `invite.invite_name_matches(f, host)` (multi-threshold OCR, see [invite-detect](invite-detect.md)); the `matched` flag must hold on `NAME_STREAK` = 2 consecutive reads (R2) before the accept tap on `accept_uv`. A mismatch resets the streak. The returned name is only logged (`last_name`). After `NAME_READS_MAX` = 5 reads without an accept, the popup is closed with `close_uv`, `invite from <name|?> -- declined` is logged, and waiting continues (1 s sleep so the popup can close).

## After accept
- Phase `joining`: no `recover` is called, because a loading screen is "unknown" to it and its BACK/relaunch would undo the accept. `join_s` for a joined room or a battle, else `'failed'`; a popup still up after `join_s` is closed with X and also `'failed'`.
- Swallowed taps (rdT10, tightened rdT11): the accept is tapped again (`accept again (n/3)`) only when the popup is seen on two consecutive frames (`popup_run >= 2`), `ACCEPT_RETRY_S` = 2 s after the last accept tap, and `invite.joined_room(f)` is false on that frame; at most `TAPS_MAX` = 3 accept taps per invite. Why: the popup stays drawn briefly after a good accept (2026-11-05 live run fired needless 2nd/3rd taps). The decline X tap works the same way: another X after 2 s, 3 X taps max, then the popup is read afresh. The decline counter resets when the popup is gone.
- Phase `room`: `room_s` without a battle -> tap `MODAL_X_UV` to leave, `'failed'`. Room not seen: that is the room -> battle loading after the host's 협동 시작, not a failure (rdT11: it outlasted the old `ROOM_GONE_S` = 5 s, so every invite round failed). Keep waiting up to `ROOM_TO_BATTLE_S` = 30 s for `board.is_battle` with no `recover`, BACK or tap; only then `'failed'` ("joined room gone -- failed"). `should_stop` is still checked each tick.
- Pause: a popup seen while pausing is declined with X, then `'paused'`.

## Dry run (`inj.execute` False)
No tap is made. After the first decision it logs `would accept` or `would decline` and returns `'stopped'`, so a dry run does not spin.

## Evidence
- `src/rdom/input/coop_join.py` (rdT11, task/rdT11) — `ROOM_TO_BATTLE_S` replaces `ROOM_GONE_S`, the `popup_run` counter and `joined_room` check on the accept re-tap; tests in `tests/test_coop_join.py`.
- commit `9c8ce09` (rdT10) — `src/rdom/input/coop_join.py` `ACCEPT_RETRY_S`, `TAPS_MAX`, the `accepts`/`declines` counters; tests in `tests/test_coop_join.py`.
- commit `09a8c4e` (branch task/rdf04-t4, not yet merged into this checkout, so paths are not lint-checked) — adds src/rdom/input/coop_join.py (constants, phases, return values, the AI-NOTE on skipping recover while joining) and tests/test_coop_join.py (fake grabber, injector and clock covering AC1-AC5).
- commit `4141695` (branch task/rdT05, not yet merged into this checkout, so paths are not lint-checked) — src/rdom/input/coop_join.py uses `invite_name_matches` in the name check; tests/test_coop_join.py monkeypatches it.
- [invite-detect](invite-detect.md) — the detectors this flow calls.
