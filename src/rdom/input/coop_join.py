"""Joiner side of duo mode: wait for the host's 게임 초대 popup, check who invited,
accept (or decline with the popup's X), join the room and wait for the battle.

One function the loop calls between games. It only taps the popup's accept / X
buttons and the room's X; everything else on the lobby is `recover`'s job.
"""
from __future__ import annotations
import time

from rdom.input.inject import MODAL_X_UV
from rdom.perception import board, invite

TICK_S = 0.5            # frame period; should_stop() is checked every tick (<= 2 s required)
NAME_READS_MAX = 5      # reads before an unreadable / foreign name is declined
NAME_STREAK = 2         # R2: two identical consecutive reads before accepting
ROOM_GONE_S = 5.0       # joined room not seen for this long -> failed
WAIT_LOG_S = 60.0


def _log(msg):
    print(msg, flush=True)


def wait_and_accept(g, inj, host, should_stop, recover, now=time.monotonic,
                    sleep=time.sleep, join_s=20, room_s=120):
    """-> 'battle' | 'failed' | 'stopped' | 'paused'.

    should_stop() returns None, 'stop' or 'pause'. recover(f) is the loop's lobby
    popup/relaunch step; it runs only on frames that are no battle, popup or room.
    'room_timeout' is not returned: a room that runs past room_s is 'failed' (the
    loop counts failed rounds).
    """
    t0 = now(); last_log = t0
    phase = "wait"            # wait -> joining (accepted) -> room (joined_room seen)
    t_accept = room_since = room_gone = None
    streak = reads = 0; last_name = ""

    def tap(uv):
        inj.tap(*uv)

    while True:
        stop = should_stop()
        if stop == "stop":
            return "stopped"
        f = g.grab()
        if stop == "pause":
            # a popup that opens while pausing is declined so it does not block the lobby
            p = invite.invite_popup(f)
            if p is not None and inj.execute:
                _log("invite while pausing -- declined"); tap(p["close_uv"])
            return "paused"
        t = now()
        if board.is_battle(f):
            return "battle"

        popup = invite.invite_popup(f)       # BEFORE recover: recover would tap the modal X on it
        if popup is not None:
            if phase == "joining":
                if t - t_accept > join_s:
                    _log("invite popup still up after accept -- failed")
                    if inj.execute:
                        tap(popup["close_uv"])
                    return "failed"
            else:
                matched, name = invite.invite_name_matches(f, host)
                reads += 1
                if name:
                    last_name = name
                streak = streak + 1 if matched else 0
                if streak >= NAME_STREAK:
                    _log(f"invite from {name} -- accept")
                    if not inj.execute:
                        _log("would accept"); return "stopped"
                    tap(popup["accept_uv"])
                    phase = "joining"; t_accept = now()
                elif reads >= NAME_READS_MAX:
                    _log(f"invite from {last_name or '?'} -- declined")
                    if not inj.execute:
                        _log("would decline"); return "stopped"
                    tap(popup["close_uv"])
                    streak = reads = 0; last_name = ""
                    sleep(1.0)               # let the popup close before the next frame
                    continue
            sleep(TICK_S); continue
        streak = reads = 0; last_name = ""   # popup gone: the next one starts a fresh read

        if invite.joined_room(f):
            room_gone = None
            if phase != "room":
                phase = "room"; room_since = t
            elif t - room_since > room_s:
                _log("room_s over without a battle -- leaving room")
                if inj.execute:
                    tap(MODAL_X_UV)
                return "failed"
        elif phase == "joining":
            # AI-NOTE: no recover() here -- a loading/transition screen is "unknown" to it
            # and its BACK / relaunch would undo the accept.
            if t - t_accept > join_s:
                _log("did not reach the room in time -- failed")
                return "failed"
        elif phase == "room":
            room_gone = t if room_gone is None else room_gone
            if t - room_gone >= ROOM_GONE_S:
                _log("joined room gone -- failed")
                return "failed"
        else:
            if recover(f):           # truthy = the loop gave up (game will not start): failed round
                _log("recover gave up -- failed")
                return "failed"
            if t - last_log >= WAIT_LOG_S:
                last_log = t
                _log(f"still waiting for an invite ({int((t - t0) // 60)} min)")
        sleep(TICK_S)
