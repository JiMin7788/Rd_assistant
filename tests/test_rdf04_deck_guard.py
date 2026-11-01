"""rdF04 t6: run_battle(expect), detect_support_deck(scales) at LD scale, duo flag on the round record."""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_bot as sb
from rdom.perception import gear, support

LD_SCALES = (1.25, 1.2, 1.15, 1.1, 1.05, 1.0)
FIX = Path(__file__).parent / "fixtures" / "ld_gear"


def _player(result):
    def p(g, inj, minutes=None):
        p.calls.append(minutes)
        return result
    p.calls = []
    p.stats = {}
    return p


def _boom_route(g):
    raise AssertionError("route called")


# ---- run_battle(expect) ----

def test_expect_none_routes_and_hands_over():
    gp, sp = _player("wrong_deck"), _player("timeout")
    assert sb.run_battle(None, None, 5, route=lambda g: "gear", gear_play=gp, support_play=sp,
                         expect=None) == ("timeout", sp)
    assert gp.calls == [5] and sp.calls == [5]


def test_expect_gear_returns_wrong_deck_without_handover_or_route():
    gp, sp = _player("wrong_deck"), _player("x")
    assert sb.run_battle(None, None, 5, route=_boom_route, gear_play=gp, support_play=sp,
                         expect="gear") == ("wrong_deck", gp)
    assert gp.calls == [5] and sp.calls == []


def test_expect_gear_plays_gear_even_if_route_says_support():
    gp, sp = _player("game_over"), _player("x")
    assert sb.run_battle(None, None, 3, route=_boom_route, gear_play=gp, support_play=sp,
                         expect="gear") == ("game_over", gp)
    assert sp.calls == []


def test_expect_support_gear_route_is_wrong_deck_and_plays_nothing():
    gp, sp = _player("x"), _player("y")
    assert sb.run_battle(None, None, 5, route=lambda g: "gear", gear_play=gp, support_play=sp,
                         expect="support") == ("wrong_deck", None)
    assert gp.calls == [] and sp.calls == []


def test_expect_support_support_route_plays_support():
    gp, sp = _player("x"), _player("game_over")
    assert sb.run_battle(None, None, 9, route=lambda g: "support", gear_play=gp, support_play=sp,
                         expect="support") == ("game_over", sp)
    assert gp.calls == [] and sp.calls == [9]


# ---- detect_support_deck at LD scale ----

def _ld_frame(name="battle_0.png", paste_scale=1 / 0.85):
    bgr = cv2.imread(str(FIX / name))
    f = gear.normalize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).copy()
    t = support._tpl("deck_support.png")
    t = cv2.resize(t, None, fx=paste_scale, fy=paste_scale, interpolation=cv2.INTER_AREA)
    h, W = f.shape[0], gear._content_w(f)
    y, x = int(0.95 * h), int(0.62 * W)
    f[y:y + t.shape[0], x:x + t.shape[1]] = t
    return f


def _score(f, scales=None):
    return support._search(f, support.DECK_BAR_BOX, support._tpl("deck_support.png"), scales)[0]


def test_ld_scale_emblem_found_with_ld_scales_only():
    # AI-NOTE: at exactly 1/0.85 the 16x88 template still reaches 0.762 with today's scales (LD scales: 0.966),
    # so the detect / not-detect split is shown at 1.3x, the top of the range the LD scales cover.
    f = _ld_frame(paste_scale=1.3)
    assert support.detect_support_deck(f, scales=LD_SCALES) is True
    assert support.detect_support_deck(f) is False


def test_ld_scales_score_clearly_higher_at_one_over_085():
    f = _ld_frame()
    assert support.detect_support_deck(f, scales=LD_SCALES) is True
    assert _score(f, LD_SCALES) > 0.95 > _score(f) + 0.1


def test_gpg_scale_emblem_still_found_by_default_and_ld_scales():
    f = _ld_frame(paste_scale=0.85 / 0.85)      # the template as cut (GPG)
    assert support.detect_support_deck(f) is True
    assert support.detect_support_deck(f, scales=LD_SCALES) is True


def test_box_argument_limits_the_search():
    f = _ld_frame()
    assert support.detect_support_deck(f, scales=LD_SCALES, box=(0.0, 0.0, 0.3, 0.3)) is False


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("battle_*.png")))
def test_no_false_positive_on_ld_gear_battle_frames(name):
    rgb = cv2.cvtColor(cv2.imread(str(FIX / name)), cv2.COLOR_BGR2RGB)
    assert support.detect_support_deck(rgb, scales=LD_SCALES) is False
    assert support.detect_support_deck(rgb) is False


def test_at_least_five_negative_frames():
    assert len(list(FIX.glob("battle_*.png"))) >= 5


# ---- gear_bot SUPPORT_SCALES ----

def test_gear_bot_support_scales_default_none_and_ld_value():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gear_bot_t6", os.path.join(
        os.path.dirname(__file__), "..", "tools", "gear_bot.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.SUPPORT_SCALES is None
    assert m.LD_SUPPORT_SCALES == LD_SCALES


# ---- play(duo) ----

class _Saver:
    def frame(self, frame, path):
        return path


class _Player:
    last_frame = None

    def __init__(self, g, inj, saver, game_id=None, tick=None, trial=False):
        self.stats = {"merges": 0, "fails": 0, "support": 0, "complete": False}
        self.milestones = sb.MilestoneTracker()
        self.power = None

    def run(self, minutes):
        return "timeout"


class _G:
    def grab(self):
        return "F"


@pytest.fixture
def rounds(monkeypatch, tmp_path):
    import support_players as sp
    path = tmp_path / "rounds.jsonl"
    monkeypatch.setattr(sb, "Saver", lambda g: _Saver())
    monkeypatch.setattr(sb, "ROUNDS_FILE", str(path))
    monkeypatch.setattr(sb.support, "gate_state", lambda: {"type": True, "pip": True})
    monkeypatch.setattr(sp, "PlayPlayer", _Player)
    return path


def _last(path):
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])


def test_play_duo_marks_the_record(rounds):
    sb.play(_G(), None, minutes=1, duo=True)
    assert _last(rounds)["duo"] is True


def test_play_default_has_no_duo_key(rounds):
    sb.play(_G(), None, minutes=1)
    assert "duo" not in _last(rounds)
