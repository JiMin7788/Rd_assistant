"""wait_and_accept with scripted frames (dicts) and monkeypatched detectors; no live input."""
import pytest

from rdom.input import coop_join
from rdom.input.coop_join import wait_and_accept
from rdom.input.inject import MODAL_X_UV
from rdom.perception import board, invite

HOST = "대변먹는자"
ACCEPT = (0.5, 0.67)
CLOSE = (0.867, 0.171)


def popup(name=HOST, modal_x=False):
    return {"popup": True, "name": name, "modal_x": modal_x}


BATTLE = {"battle": True}
ROOM = {"room": True, "modal_x": True}
LOBBY = {}


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Grabber:
    """Returns the scripted frames in order, then repeats the last one."""
    def __init__(self, frames):
        self.frames = list(frames); self.i = 0

    def grab(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f


class Inj:
    def __init__(self, execute=True):
        self.execute = execute; self.taps = []

    def tap(self, u, v):
        self.taps.append((u, v))


@pytest.fixture(autouse=True)
def detectors(monkeypatch):
    monkeypatch.setattr(board, "is_battle", lambda f: f.get("battle", False))
    monkeypatch.setattr(invite, "invite_popup",
                        lambda f: {"accept_uv": ACCEPT, "close_uv": CLOSE} if f.get("popup") else None)
    monkeypatch.setattr(invite, "invite_name_matches",
                        lambda f, host: (invite.name_matches(f.get("name", ""), host), f.get("name", "")))
    monkeypatch.setattr(invite, "joined_room", lambda f: f.get("room", False))


def run(frames, execute=True, stop=lambda: None, recover=None, **kw):
    clk = Clock(); inj = Inj(execute); calls = []
    rec = recover or (lambda f: calls.append(f))
    res = wait_and_accept(Grabber(frames), inj, HOST, stop, rec, now=clk.now, sleep=clk.sleep, **kw)
    return res, inj, calls, clk


def test_popup_handled_before_recover(capsys):
    # AC1: popup + modal X on the same frame -> recover (which would tap the modal X) never runs
    def boom(f):
        raise AssertionError("recover called")
    res, inj, _, _ = run([popup(modal_x=True)] * 2 + [BATTLE], recover=boom)
    assert res == "battle"
    assert inj.taps == [ACCEPT]
    assert f"invite from {HOST} -- accept" in capsys.readouterr().out


def test_accept_needs_two_consecutive_matches():
    # AC2: match, mismatch, match does not accept; the streak restarts after the mismatch
    res, inj, _, _ = run([popup(), popup("배속봇"), popup(), BATTLE])
    assert res == "battle" and inj.taps == []
    res, inj, _, _ = run([popup(), popup(), BATTLE])
    assert inj.taps == [ACCEPT]


def test_foreign_name_declined_and_waiting_continues(capsys):
    # AC3
    res, inj, calls, _ = run([popup("배속봇")] * 5 + [LOBBY, BATTLE])
    assert res == "battle"
    assert inj.taps == [CLOSE]
    assert calls                       # went back to recover() on the lobby frame
    assert "invite from 배속봇 -- declined" in capsys.readouterr().out


def test_unreadable_name_declined_after_five_reads(capsys):
    res, inj, _, _ = run([popup("")] * 4 + [LOBBY, BATTLE])
    assert inj.taps == []              # 4 reads: still reading
    res, inj, _, _ = run([popup("")] * 5 + [LOBBY, BATTLE])
    assert inj.taps == [CLOSE]
    assert "invite from ? -- declined" in capsys.readouterr().out


def test_no_room_within_join_s_fails():
    # AC4: accepted, then nothing but the lobby
    res, inj, calls, clk = run([popup()] * 2 + [LOBBY], join_s=20)
    assert res == "failed" and inj.taps == [ACCEPT]
    assert not calls                   # recover must not run during the join
    assert 20 < clk.t < 25


def test_popup_still_up_after_join_s_fails():
    res, inj, _, _ = run([popup()], join_s=10)
    assert res == "failed"
    assert inj.taps == [ACCEPT, ACCEPT, ACCEPT, CLOSE]     # rdT10: 3 accept taps, then the failure X


def test_accept_retapped_after_2s_up_to_3_taps(capsys):
    res, inj, _, clk = run([popup()], join_s=20)
    out = capsys.readouterr().out
    assert inj.taps[:3] == [ACCEPT] * 3 and res == "failed"
    assert "accept again (2/3)" in out and "accept again (3/3)" in out and "accept again (4/3)" not in out


def test_accept_not_retapped_when_popup_goes_within_2s():
    res, inj, _, _ = run([popup()] * 2 + [ROOM] + [BATTLE])
    assert res == "battle" and inj.taps == [ACCEPT]


def test_decline_x_retapped_after_2s_max_3(capsys):
    n = [0]
    def stop():
        n[0] += 1
        return "stop" if n[0] > 40 else None
    res, inj, _, clk = run([popup("엉뚱한")], stop=stop)
    assert res == "stopped" and inj.taps[:3] == [CLOSE] * 3
    assert "decline again (2/3)" in capsys.readouterr().out


def test_room_gone_waits_for_the_battle_without_recover_or_taps():
    # rdT11: the room disappearing is the room -> battle loading, not a failure
    def boom(f):
        raise AssertionError("recover called")
    res, inj, _, clk = run([popup()] * 2 + [ROOM] * 3 + [LOBBY] * 40 + [BATTLE], recover=boom)
    assert res == "battle" and inj.taps == [ACCEPT]
    assert 15 < clk.t < coop_join.ROOM_TO_BATTLE_S


def test_room_gone_for_30s_fails_without_recover_or_taps():
    calls = []
    res, inj, _, clk = run([popup()] * 2 + [ROOM] * 3 + [LOBBY], recover=lambda f: calls.append(f))
    assert res == "failed" and coop_join.ROOM_TO_BATTLE_S == 30.0
    assert inj.taps == [ACCEPT] and calls == []        # room already gone: no X tap, no recover
    assert 30 <= clk.t < 40


def test_accept_not_retapped_when_the_frame_shows_the_room(capsys):
    # popup drawn on two frames >= 2 s after the tap, but the join already shows (room frame) -> no re-tap
    frames = [popup()] * 2 + [LOBBY] * 0 + [ROOM] * 6 + [BATTLE]
    res, inj, _, _ = run(frames)
    assert res == "battle" and inj.taps == [ACCEPT] and "accept again" not in capsys.readouterr().out


def test_accept_retap_needs_two_consecutive_popup_frames_and_no_room(monkeypatch):
    # popup frame, then a lobby frame (streak broken), popup again: each popup frame alone never re-taps
    seq = [popup()] * 2 + [LOBBY, popup()] * 10
    res, inj, _, _ = run(seq + [BATTLE])
    assert inj.taps == [ACCEPT]
    # a popup frame that also reports joined_room is never re-tapped
    both = {"popup": True, "name": HOST, "room": True}
    res, inj, _, _ = run([popup()] * 2 + [both] * 10 + [BATTLE])
    assert res == "battle" and inj.taps == [ACCEPT]


def test_room_s_runs_out_fails_and_leaves_room():
    res, inj, _, clk = run([popup()] * 2 + [ROOM], room_s=30)
    assert res == "failed"
    assert inj.taps == [ACCEPT, MODAL_X_UV]
    assert 30 < clk.t < 40


def test_battle_in_room():
    res, inj, _, _ = run([popup()] * 2 + [ROOM] * 4 + [BATTLE])
    assert res == "battle" and inj.taps == [ACCEPT]


def test_stop_returns_within_2s():
    # AC5
    clk = Clock()
    stop = lambda: "stop" if clk.t >= 10 else None
    inj = Inj()
    res = wait_and_accept(Grabber([LOBBY]), inj, HOST, stop, lambda f: None,
                          now=clk.now, sleep=clk.sleep)
    assert res == "stopped" and 10 <= clk.t < 12 and inj.taps == []


def test_pause_declines_open_popup():
    res, inj, _, _ = run([popup()], stop=lambda: "pause")
    assert res == "paused" and inj.taps == [CLOSE]
    res, inj, _, _ = run([LOBBY], stop=lambda: "pause")
    assert res == "paused" and inj.taps == []


def test_dry_run_accept_makes_no_tap(capsys):
    res, inj, _, _ = run([popup()] * 3, execute=False)
    out = capsys.readouterr().out
    assert res == "stopped" and inj.taps == []
    assert "would accept" in out


def test_dry_run_decline_makes_no_tap(capsys):
    res, inj, _, _ = run([popup("배속봇")] * 6, execute=False)
    assert res == "stopped" and inj.taps == []
    assert "would decline" in capsys.readouterr().out


def test_still_waiting_log_every_minute(capsys):
    clk = Clock()
    stop = lambda: "stop" if clk.t >= 130 else None
    wait_and_accept(Grabber([LOBBY]), Inj(), HOST, stop, lambda f: None, now=clk.now, sleep=clk.sleep)
    out = capsys.readouterr().out
    assert "still waiting for an invite (1 min)" in out
    assert "still waiting for an invite (2 min)" in out
