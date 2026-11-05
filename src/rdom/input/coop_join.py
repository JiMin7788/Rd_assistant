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
# AI-NOTE: the joined room disappearing is the room -> battle loading screen after the host's 협동 시작, which
# lasted well over the old 5 s (2026-11-05: every invite round failed); wait this long for the battle.
ROOM_TO_BATTLE_S = 30.0
WAIT_LOG_S = 60.0
ACCEPT_RETRY_S = 2.0    # popup still up this long after an accept / X tap -> the tap was swallowed, tap again
TAPS_MAX = 3            # at most this many accept taps (and X taps) per invite


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
    accepts = declines = 0; t_tap = t_decline = t0      # taps so far / time of the last accept or X tap
    popup_run = 0             # consecutive popup frames while joining (an accept re-tap needs two)

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
            if phase == "wait" and declines:
                # AI-NOTE: a swallowed X tap leaves the popup up: tap X again after ACCEPT_RETRY_S (max 3 taps)
                if t - t_decline < ACCEPT_RETRY_S:
                    sleep(TICK_S); continue
                if declines < TAPS_MAX:
                    declines += 1; t_decline = now()
                    _log(f"decline again ({declines}/{TAPS_MAX})")
                    tap(popup["close_uv"])
                    sleep(TICK_S); continue
                declines = 0                 # 3 X taps did not close it: read the popup afresh
            if phase == "joining":
                if t - t_accept > join_s:
                    _log("invite popup still up after accept -- failed")
                    if inj.execute:
                        tap(popup["close_uv"])
                    return "failed"
                popup_run += 1
                # AI-NOTE: the accept tap can be swallowed (window activation race), but the popup stays drawn
                # for a moment even after a good accept (2026-11-05: needless 2nd/3rd taps): re-tap only on two
                # consecutive popup frames, ACCEPT_RETRY_S after the last tap, with no sign of the room.
                if (accepts < TAPS_MAX and popup_run >= 2 and t - t_tap >= ACCEPT_RETRY_S
                        and not invite.joined_room(f)):
                    accepts += 1; t_tap = now(); popup_run = 0
                    _log(f"accept again ({accepts}/{TAPS_MAX})")
                    tap(popup["accept_uv"])
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
                    phase = "joining"; t_accept = t_tap = now(); accepts = 1
                elif reads >= NAME_READS_MAX:
                    _log(f"invite from {last_name or '?'} -- declined")
                    if not inj.execute:
                        _log("would decline"); return "stopped"
                    tap(popup["close_uv"])
                    declines = 1; t_decline = now()
                    streak = reads = 0; last_name = ""
                    sleep(1.0)              # let the popup close before the next frame
                    continue
            sleep(TICK_S); continue
        streak = reads = 0; last_name = ""   # popup gone: the next one starts a fresh read
        declines = popup_run = 0

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
            # AI-NOTE: no recover(), BACK or tap here -- the room -> battle loading screen is "unknown" to them.
            room_gone = t if room_gone is None else room_gone
            if t - room_gone >= ROOM_TO_BATTLE_S:
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
