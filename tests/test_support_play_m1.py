"""rdf02-m1: Joker/bomb merge memory drop (R7.1) and bursts under a covered window (R5, R8, R9), fake-based."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_players as sp
import support_bot
from rdom.perception import collect
from test_support_play_memory import (FakeClock, FakeGrabber, FakeInjector, FakePerception, RE3,  # noqa: F401
                                      no_fail_crops, rd, spy_merged, ticks, uses)

JO3, BOMB, AD1, RE4 = ("Joker", 3), ("Bomb", 0), ("Adjust", 1), ("Resonance", 4)


class Saver:
    def __init__(self):
        self.bursts = []

    def cells(self, *a, **kw):
        pass

    def frame(self, *a, **kw):
        pass

    def burst(self, game_id, t, cells, grabs, record):
        self.bursts.append(record)
        return ["n"]


def make(boards, saver=None, grabber=None):
    clock = FakeClock()
    perc = FakePerception(boards)
    inj, saver = FakeInjector(), saver or Saver()
    p = sp.PlayPlayer(grabber or FakeGrabber(), inj, saver, perc=perc, game_id="G", clock=clock,
                      sleep=clock.sleep)
    return p, inj, perc, saver


# ---- AC1: a Joker copy / bomb merge drops both memories like a normal merge ----

@pytest.mark.parametrize("name,first,second,after", [
    ("joker", {1: JO3, 2: RE3}, {1: JO3, 2: RE3}, {1: None, 2: RE4}),
    ("bomb", {1: BOMB, 2: BOMB}, {1: BOMB, 2: BOMB}, {1: None, 2: AD1}),
])
def test_joker_copy_and_bomb_merge_drop_both_memories(name, first, second, after):
    p, inj, perc, _ = make([first, second, after])
    calls = spy_merged(p)
    ticks(p, 2)
    assert len(inj.swipes) == 1 and uses(inj.swipes[0], 1) and uses(inj.swipes[0], 2)
    assert tuple(inj.swipes[0][:2]) != tuple(inj.swipes[0][2:4])
    assert p._pending[:2] == [1, 2] and p.memory.memory(1) == first[1] and p.memory.memory(2) == first[2]
    ticks(p, 1)                                            # cell 1 confidently empty: verdict 'effect'
    assert calls == [(1, 2)] and p._pending is None
    assert p.memory.memory(1) is None and p.memory.memory(2) is None
    assert 1 not in p.memory._pend and 2 not in p.memory._pend    # the half-confirmed new reads are gone too
    assert p.stats["fails"] == 0


# ---- AC2: a covered window still bursts, but nothing is written or counted ----

class CoveredGrabber(FakeGrabber):
    def unobscured(self):
        return False


@pytest.mark.parametrize("saved_before", [0, sp.BURST_SAVE_MAX - 1])
def test_covered_window_burst_runs_but_saves_and_counts_nothing(tmp_path, monkeypatch, capsys, saved_before):
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path))
    writes = []
    monkeypatch.setattr(collect.cv2, "imwrite", lambda *a, **k: writes.append(a))
    g = CoveredGrabber()
    p, inj, perc, _ = make([{3: None, 1: RE3, 5: "junk"}], saver=support_bot.Saver(g), grabber=g)
    perc.burst_script[5] = [rd(RE3)] * 6
    planned = []
    orig = sp.plan_support
    monkeypatch.setattr(sp, "plan_support", lambda b, *a, **kw: (planned.append(b), orig(b, *a, **kw))[1])
    p.burster.saved = saved_before
    ticks(p, 1)
    out = capsys.readouterr().out
    assert "burst cells 5 -> 5=Re3 (6 of 6 grabs)" in out
    assert p.stats["bursts"] == 1 and p.stats["burst_hits"] == 1
    cell5 = planned[0][4]                                   # the plan of the same tick sees the burst value
    assert (cell5["src"], cell5["type"], cell5["pip"]) == ("burst", "Resonance", 3)
    assert p.memory.memory(5) == RE3
    assert not list(tmp_path.rglob("*")) and writes == []   # no burst file, no bursts.jsonl
    assert p.burster.saved == saved_before and p.burster.last_save == -1e9
    assert os.path.exists(os.path.join(str(tmp_path), "_burst", "bursts.jsonl")) is False
