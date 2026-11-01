---
title: Inviter flow (invite_and_start)
type: component
updated: 2026-11-01
sources: [rdf04-t5, rdf04-i2]
---
# Inviter flow (invite_and_start)

`rdom.input.friend_coop.invite_and_start` is the gear bot's duo lobby step: open a room, invite the partner by name, keep the invite alive up to `wait_s`, tap 협동 시작 once they are in. Not wired into `gear_loop` yet (rdf04-t8). The joiner side is [coop-join](coop-join.md).

## Contract
`invite_and_start(grab, inj, name, wait_s=300, should_stop, uv=None, now, sleep)` returns `True` (start tapped) | `False` (`wait_s` over, room left with MODAL_X) | `None` (not on the lobby / friend menu / coop room, a menu/room did not open, or navigation broke) | `'stopped'` / `'paused'` (`should_stop()` said `'stop'` / `'pause'`, room left with MODAL_X). `uv` overrides the tap keys FRIEND, CREATE_ROOM, INVITE_FRIEND, START_COOP, CLOSE_X, MODAL_X (defaults are the `inject.py` constants). `now`/`sleep` are injectable so tests run on a fake clock.

## Behaviour
- Setup steps are gated like `start_friend_coop`, but the start screen decides where to begin (one frame): coop room -> go straight to the invite; 친구와 하기 menu -> tap 방 생성 first; lobby -> 친구와 하기 (5 s), 방 생성 (5 s); anything else -> `None`. This matches where `gear_loop.recover_step` ends (coop room or the friend menu), so a crash/restart while waiting in the room no longer fails every following round. Then 친구 초대 + `find_friend_in_popup` (4 OCR tries, 0.5 s apart).
- Wait loop, one pass per `TICK_S` = 0.5 s (so a stop request is honoured well inside 2 s). Per frame: `start_ready` -> tap START_COOP once, `True`. Not in the coop room for `ROOM_GONE_S` = 5 s -> `None`. `slot_pending` (수락 대기중) -> keep waiting.
- Expiry: when the slot shows neither pending nor ready for `EXPIRED_S` = 3 s, it logs `invite expired -- inviting again` and invites again. The first invite goes out as soon as the room is up. A failed invite (friend list did not open / name not found) sleeps 3 s and tries again until `wait_s`.
- No room code is read, written or posted on this path (a test checks the function body for `read_room_code`, `write_room`, `send_room_code`).

## Decision: separate implementation
`start_friend_coop` and `open_room_and_wait` are untouched (their 60 s wait and retry caps are live-tested); `invite_and_start` re-implements the gated steps on an injectable clock instead of refactoring them into shared helpers (AI-NOTE in the code).

## Tests
`tests/test_friend_coop_invite.py` uses a `Sim` whose screen follows the taps, monkeypatched detectors and a fake clock. It covers re-invite on expiry, no re-send while pending, one start tap, `wait_s` over, stop/pause, unknown screen, start from an open coop room and from the friend menu (no FRIEND tap), navigation broke, friend not found, uv override, and one pass over the LD fixtures `ld_host_pending` (slot_pending, not start_ready) and `ld_host_joined_start_ready` (start_ready).

## Evidence
- commit `3862b33` (branch task/rdf04-t5, not yet merged into this checkout, so paths are not lint-checked) — adds `invite_and_start`, `TICK_S`/`EXPIRED_S`/`ROOM_GONE_S`, `_uv_map`, `_wait_until` to src/rdom/input/friend_coop.py and tests/test_friend_coop_invite.py.
- commit `9c8b45e` (rdf04-i2) — src/input/friend_coop.py `invite_and_start` branches on is_coop_room / is_friend_menu / is_lobby; tests/test_friend_coop_invite.py `test_starts_from_an_open_coop_room`, `test_starts_from_the_friend_menu`, `test_unknown_screen_is_none`; tests/test_gear_loop_roles.py `test_inviter_starts_from_a_coop_room_frame`.
- [coop-join](coop-join.md) — the joiner side of the duo lobby.
