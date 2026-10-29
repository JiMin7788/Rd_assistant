"""Dice info panel ('정렬 주사위' stats screen opened by tapping a field die): detector on real
frames (downscaled to 311x556 under tests/fixtures) and the support tick handler (one 소환 tap)."""
import os
import sys

import cv2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from rdom.perception import gear
from rdom.perception.gear import UI
import support_players as sp
from test_support_play_player import FakeClock, FakeGrabber, FakeInjector, FakePerception, MERGE

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    return cv2.cvtColor(cv2.imread(os.path.join(FIX, name)), cv2.COLOR_BGR2RGB)


@pytest.mark.parametrize("name", ["dice_info_banner.png", "dice_info_plain.png"])
def test_detector_true_on_info_panel(name):
    # banner variant is the 2026-10-30 06:43 frame (boss banner over the middle, board dimmed)
    f = load(name)
    assert gear.dice_info_panel(f), gear.dice_info_scores(f)


@pytest.mark.parametrize("name", ["neg_battle.png", "neg_power_panel.png", "neg_banner.png",
                                  "neg_banner2.png", "neg_dark_lower.png"])
def test_detector_false_on_other_frames(name):
    f = load(name)
    assert not gear.dice_info_panel(f), gear.dice_info_scores(f)


class InfoPerception(FakePerception):
    def __init__(self):
        super().__init__(MERGE)
        self.info = True
        self.board_reads = 0

    def dice_info_panel(self, f):
        return self.info

    def read_board_support(self, f, pip_source="auto"):
        self.board_reads += 1
        return super().read_board_support(f, pip_source)


class CountSaver:
    def __init__(self):
        self.calls = []

    def cells(self, *a, **kw):
        self.calls.append("cells")

    def frame(self, *a, **kw):
        self.calls.append("frame")

    def burst(self, *a, **kw):
        self.calls.append("burst")


def make():
    clock = FakeClock()
    perc, saver = InfoPerception(), CountSaver()
    inj = FakeInjector()
    p = sp.PlayPlayer(FakeGrabber(), inj, saver, perc=perc, game_id="G", clock=clock,
                      sleep=clock.sleep, tick=0.6)
    return p, inj, perc, saver, clock


def test_panel_taps_summon_once_without_board_side_effects(capsys):
    p, inj, perc, saver, clock = make()
    p.tick()
    assert inj.taps == [UI["summon"]]
    assert inj.swipes == []
    assert perc.board_reads == 0 and saver.calls == []
    assert p.battle_start is None and p.memory.state(1) != "remembered"
    assert "dice info panel -> 소환 (close)" in capsys.readouterr().out


def test_panel_still_up_after_0_3s_does_not_tap_again():
    p, inj, perc, saver, clock = make()
    p.tick()
    clock.sleep(0.3)
    p.tick()
    assert inj.taps == [UI["summon"]]


def test_panel_still_up_after_1s_taps_again():
    p, inj, perc, saver, clock = make()
    p.tick()
    clock.sleep(1.0)
    p.tick()
    assert inj.taps == [UI["summon"], UI["summon"]]
    assert perc.board_reads == 0 and inj.swipes == []


def test_board_play_resumes_when_panel_is_closed():
    p, inj, perc, saver, clock = make()
    p.tick()
    perc.info = False
    clock.sleep(0.6)
    p.tick()
    assert perc.board_reads == 1
    assert inj.taps == [UI["summon"]]
