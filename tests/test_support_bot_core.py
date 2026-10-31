import datetime
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_bot as sb
from rdom.perception import collect


class FakeGrabber:
    def __init__(self, unobscured=True):
        self.n = 0
        self.flag = unobscured

    def grab(self):
        self.n += 1
        return self.n

    def unobscured(self):
        return self.flag


def test_route_forced(capsys):
    def boom(f):
        raise AssertionError("detect called")
    assert sb.route_deck(FakeGrabber(), detect=boom, force=lambda: "support") == "support"
    assert "deck route: support (forced by deck.toml)" in capsys.readouterr().out


def test_route_bar(capsys):
    sleeps = []
    r = sb.route_deck(FakeGrabber(), detect=lambda f: f in (3, 4), force=lambda: "",
                      sleep=sleeps.append)
    assert r == "support"
    assert "deck route: support (deck bar)" in capsys.readouterr().out
    assert sleeps == [0.5, 0.5, 0.5]


def test_route_gear(capsys):
    g = FakeGrabber()
    sleeps = []
    r = sb.route_deck(g, detect=lambda f: f in (3, 5), force=lambda: "", sleep=sleeps.append)
    assert r == "gear" and g.n == 20
    assert "deck route: gear" in capsys.readouterr().out
    assert set(sleeps) == {0.5} and len(sleeps) == 19


@pytest.mark.parametrize("gates,mode,line", [
    ({"type": False, "pip": False}, "collect", "support deck: collect mode (type gate not passed)"),
    ({"type": False, "pip": True}, "collect", "support deck: collect mode (type gate not passed)"),
    ({"type": True, "pip": False}, "trial", "support deck: trial mode (type gate PASS, pip gate FAIL)"),
    ({"type": True, "pip": True}, "play", "support deck: play mode (type gate PASS, pip gate PASS)"),
])
def test_choose_mode(gates, mode, line):
    assert sb.choose_mode(gates) == (mode, line)


def test_saver_unobscured_each_call(monkeypatch):
    calls = []
    monkeypatch.setattr(collect, "save_support_cells",
                        lambda frame, gid, t, unobscured, **kw: calls.append(("cells", unobscured)))
    monkeypatch.setattr(collect, "save_frame",
                        lambda frame, path, unobscured: calls.append(("frame", unobscured)))
    g = FakeGrabber()
    s = sb.Saver(g)
    s.cells("f", "gid", 1.0)
    g.flag = False
    s.cells("f", "gid", 2.0)
    s.frame("f", "p.png")
    assert calls == [("cells", True), ("cells", False), ("frame", False)]


def test_saver_writes_nothing_when_covered(tmp_path):
    g = FakeGrabber(unobscured=False)
    p = tmp_path / "x" / "f.png"
    img = np.zeros((4, 4, 3), np.uint8)
    assert sb.Saver(g).frame(img, str(p)) is None
    assert not p.exists()
    g.flag = True
    assert sb.Saver(g).frame(img, str(p)) == str(p)
    assert p.exists()


def test_new_game_id():
    assert sb.new_game_id(datetime.datetime(2026, 11, 2, 20, 15, 0)) == "sup20261102_201500"


def test_build_and_append(tmp_path):
    ms = {"milestones": {"m1": {}}, "crossings": {"2000": {}}, "max_score": 2500, "scores_confirmed": 7}
    t0 = datetime.datetime(2026, 11, 2, 20, 0, 0)
    rec = sb.build_record("sup1", t0, t0, "game_over", "trial", {"type": True, "pip": False},
                          ms, None, {"merges": 3})
    assert set(rec) == {"game_id", "wall_start", "wall_end", "result", "mode", "gates", "max_score",
                        "scores_confirmed", "milestones", "crossings", "power", "stats", "final_score"}
    assert rec["power"] is None and rec["max_score"] == 2500
    path = tmp_path / "new" / "r.jsonl"
    sb.append_round(str(path), rec)
    sb.append_round(str(path), rec)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["game_id"] == "sup1"


def _player(result):
    def p(g, inj, minutes=None):
        p.calls.append(minutes)
        return result
    p.calls = []
    p.stats = {}
    return p


def test_run_battle_gear():
    gp, sp = _player("game_over"), _player("x")
    assert sb.run_battle(None, None, 7, route=lambda g: "gear", gear_play=gp, support_play=sp) == ("game_over", gp)
    assert gp.calls == [7] and sp.calls == []


def test_run_battle_support():
    gp, sp = _player("a"), _player("game_over")
    assert sb.run_battle(None, None, 9, route=lambda g: "support", gear_play=gp, support_play=sp) == ("game_over", sp)
    assert gp.calls == [] and sp.calls == [9]


def test_run_battle_wrong_deck_handover():
    gp, sp = _player("wrong_deck"), _player("timeout")
    assert sb.run_battle(None, None, 5, route=lambda g: "gear", gear_play=gp, support_play=sp) == ("timeout", sp)
    assert gp.calls == [5] and sp.calls == [5]
