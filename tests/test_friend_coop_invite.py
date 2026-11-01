"""invite_and_start with a simulated game (taps change the screen) and a fake clock; no live input."""
from pathlib import Path

import cv2
import pytest

from rdom.input import friend_coop
from rdom.input.friend_coop import invite_and_start, slot_pending, start_ready
from rdom.input.inject import (FRIEND_UV, CREATE_ROOM_UV, INVITE_FRIEND_UV,
                               START_COOP_UV, MODAL_X_UV, CLOSE_X_UV)
from rdom.perception import board

NAME = "배속봇"
ROW = (0.5, 0.3)
FIX = Path(__file__).resolve().parent / "fixtures" / "rdf04"


class Sim:
    """Screen state follows the taps; `pending_for` seconds after a friend pick the slot shows
    수락 대기중, then the invite expires. `accept_at` (fake time) makes the start button ready."""
    def __init__(self, pending_for=60.0, accept_at=None, find=True):
        self.t = 0.0
        self.screen = "lobby"
        self.pending_until = -1.0
        self.pending_for, self.accept_at, self.find = pending_for, accept_at, find
        self.taps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def grab(self):
        self.t += 0.01
        return {"screen": self.screen, "pending": self.t < self.pending_until,
                "ready": self.accept_at is not None and self.t >= self.accept_at
                         and self.screen == "room"}

    def tap(self, u, v):
        uv = (u, v)
        self.taps.append(uv)
        if uv == FRIEND_UV:
            self.screen = "menu"
        elif uv == CREATE_ROOM_UV:
            self.screen = "room"
        elif uv == INVITE_FRIEND_UV:
            self.screen = "popup"
        elif uv == ROW:
            self.screen = "room"
            self.pending_until = self.t + self.pending_for
        elif uv == CLOSE_X_UV:
            self.screen = "room"
        elif uv == MODAL_X_UV:
            self.screen = "lobby"


@pytest.fixture(autouse=True)
def detectors(monkeypatch):
    monkeypatch.setattr(board, "is_lobby", lambda f: f["screen"] == "lobby")
    monkeypatch.setattr(board, "is_friend_menu", lambda f: f["screen"] == "menu")
    monkeypatch.setattr(board, "is_coop_room", lambda f: f["screen"] == "room")
    monkeypatch.setattr(board, "has_popup_close", lambda f: f["screen"] == "popup")
    monkeypatch.setattr(friend_coop, "slot_pending", lambda f: f["pending"])
    monkeypatch.setattr(friend_coop, "start_ready", lambda f: f["ready"])
    monkeypatch.setattr(friend_coop, "find_friend_in_popup",
                        lambda f, n: ROW if f["screen"] == "popup" else None)


def run(sim, **kw):
    return invite_and_start(sim, sim, NAME, now=sim.now, sleep=sim.sleep, **kw)


def test_expired_invite_is_sent_again(capsys):
    # AC2: pending for 10 s, then neither pending nor ready -> after >= 3 s a second 친구 초대
    sim = Sim(pending_for=10.0, accept_at=16.0)
    assert run(sim) is True
    assert sim.taps.count(INVITE_FRIEND_UV) == 2
    assert "invite expired -- inviting again" in capsys.readouterr().out


def test_pending_invite_is_not_resent():
    sim = Sim(pending_for=60.0, accept_at=20.0)
    assert run(sim) is True
    assert sim.taps.count(INVITE_FRIEND_UV) == 1


def test_start_ready_taps_start_once():
    # AC3
    sim = Sim(accept_at=5.0)
    assert run(sim) is True
    assert sim.taps.count(START_COOP_UV) == 1 and sim.taps[-1] == START_COOP_UV


def test_wait_s_over_leaves_room():
    # AC3
    sim = Sim(pending_for=1000.0)
    assert run(sim, wait_s=30) is False
    assert sim.taps[-1] == MODAL_X_UV and START_COOP_UV not in sim.taps


@pytest.mark.parametrize("what,res", [("stop", "stopped"), ("pause", "paused")])
def test_stop_while_waiting(what, res):
    # AC4: the stop request lands at fake t=20 and is honoured within 2 s
    sim = Sim(pending_for=1000.0)
    t_req = 20.0
    out = run(sim, should_stop=lambda: what if sim.t >= t_req else None)
    assert out == res
    assert sim.taps[-1] == MODAL_X_UV
    assert sim.t - t_req < 2.0


def test_unknown_screen_is_none():
    sim = Sim(); sim.screen = "unknown"
    assert run(sim) is None and sim.taps == []


def test_starts_from_an_open_coop_room():
    # recover_step ends on a coop room: skip 친구와 하기 / 방 생성, go straight to the invite
    sim = Sim(accept_at=10.0); sim.screen = "room"
    assert run(sim) is True
    assert FRIEND_UV not in sim.taps and CREATE_ROOM_UV not in sim.taps
    assert sim.taps.count(INVITE_FRIEND_UV) == 1


def test_starts_from_the_friend_menu():
    sim = Sim(accept_at=10.0); sim.screen = "menu"
    assert run(sim) is True
    assert FRIEND_UV not in sim.taps and sim.taps[0] == CREATE_ROOM_UV


def test_navigation_broke_is_none():
    sim = Sim(pending_for=1000.0)
    real = sim.grab
    def grab():
        f = real()
        if sim.t > 10:
            f["screen"] = "unknown"
        return f
    sim.grab = grab
    assert run(sim) is None
    assert 10 < sim.t < 20


def test_friend_not_found_retries_until_wait_s(monkeypatch):
    sim = Sim()
    monkeypatch.setattr(friend_coop, "find_friend_in_popup", lambda f, n: None)
    assert run(sim, wait_s=40) is False
    assert sim.taps.count(INVITE_FRIEND_UV) >= 2


def test_uv_override_and_no_room_code(monkeypatch):
    sim = Sim(accept_at=5.0)
    assert run(sim, uv={"START_COOP": (0.1, 0.2)}) is True
    assert sim.taps[-1] == (0.1, 0.2)
    src = Path(friend_coop.__file__).read_text(encoding="utf-8")
    body = src[src.index("def invite_and_start"):src.index("def open_room_and_wait")]
    for banned in ("read_room_code", "write_room", "send_room_code"):
        assert banned not in body


def load(n):
    img = cv2.imread(str(FIX / f"{n}.png"))
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def test_ld_fixtures_pending_and_ready():
    pend = load("ld_host_pending")
    ready = load("ld_host_joined_start_ready")
    assert slot_pending(pend) and not start_ready(pend)
    assert start_ready(ready)
