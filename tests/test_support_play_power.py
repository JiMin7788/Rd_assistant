import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
import support_bot as sb
import support_players as sp
from rdom.perception.gear import UI
from rdom.policy.milestones import MilestoneTracker
from rdom.policy.power import PowerConfig, PowerTracker
from test_support_play_player import (COMPLETE, BUTTONS, FakeClock, FakeGrabber, FakeInjector,
                                      FakePerception, board)

CARDS = {"Growth": (0.13, 0.9), "Alignment": (0.35, 0.9), "Resonance": (0.57, 0.9)}


class RecSaver:
    """Records every frame save; `ret` is what a covered window would return (None)."""

    def __init__(self, covered=False, log=None):
        self.saved, self.covered, self.log = [], covered, log

    def cells(self, *a, **kw):
        pass

    def frame(self, frame, path):
        self.saved.append((frame, path))
        if self.log is not None:
            self.log.append(("frame", path))
        return None if self.covered else path


class PowerPerception(FakePerception):
    def __init__(self, spec=None, close_after=1):
        super().__init__(spec, close_after)
        self.cards = dict(CARDS)
        self.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}   # card -> list of scripted reads (last one repeats)
        self.level_calls = []
        self.scores = []

    def power_cards(self, f):
        return dict(self.cards)

    def card_level(self, f, button):
        self.level_calls.append((f, button))
        card = next(c for c, uv in CARDS.items() if uv == button)
        seq = self.levels[card]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def read_score(self, f):
        return self.scores.pop(0) if len(self.scores) > 1 else (self.scores[0] if self.scores else None)


def make(spec=None, trial=False, covered=False, close_after=1):
    clock = FakeClock()
    log = []
    perc = PowerPerception(spec, close_after)
    g = FakeGrabber()
    inj = FakeInjector(lambda uv: (log.append(("tap", uv)), perc.on_tap(uv)))
    saver = RecSaver(covered, log)
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock.sleep(s)

    p = sp.PlayPlayer(g, inj, saver, perc=perc, game_id="G", clock=clock, sleep=sleep, tick=0.6,
                      trial=trial, power_cfg=PowerConfig())
    p.sleeps, p.log = sleeps, log
    return p, g, inj, perc, saver, clock


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def opens(inj):
    return inj.taps.count(UI["power_open"])


# ---- AC1 power bar -------------------------------------------------------------------------

def wait_plan(monkeypatch):
    monkeypatch.setattr(sp, "plan_support", lambda *a, **kw: {"op": "wait", "why": "test"})


def test_power_bar_taps_on_wait_every_20s(monkeypatch):
    wait_plan(monkeypatch)
    p, g, inj, perc, saver, clock = make()
    ticks(p, 2)                                             # second read confirms the board
    assert opens(inj) == 1
    ticks(p, 30)                                            # 18 s later: still inside the 20 s
    assert opens(inj) == 1
    ticks(p, 5)
    assert opens(inj) == 2


def test_power_bar_taps_when_field_complete(monkeypatch):
    monkeypatch.setattr(sp, "plan_support", lambda *a, **kw: {"op": "summon"})
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 2)
    assert opens(inj) == 1                                  # not a wait plan: only "complete" opens it


def test_power_bar_not_tapped_when_neither_wait_nor_complete(monkeypatch):
    monkeypatch.setattr(sp, "plan_support", lambda *a, **kw: {"op": "summon"})
    p, g, inj, perc, saver, clock = make()
    ticks(p, 5)
    assert opens(inj) == 0
    assert UI["summon"] in inj.taps


def test_power_bar_respects_hold_deadline(monkeypatch):
    wait_plan(monkeypatch)
    p, g, inj, perc, saver, clock = make()
    p.hold_power_until = clock.t + 10.0                      # set by the sp_double_later banner
    ticks(p, 10)                                            # 6 s
    assert opens(inj) == 0
    ticks(p, 10)                                            # past the deadline
    assert opens(inj) == 1


def test_power_bar_gap_counts_from_the_visit(monkeypatch):
    wait_plan(monkeypatch)
    p, g, inj, perc, saver, clock = make()
    ticks(p, 2)
    perc.panel = True
    ticks(p, 1)                                             # a visit (no cards found, closes)
    perc.panel = False
    n = opens(inj)
    ticks(p, 20)
    assert opens(inj) == n                                  # < 20 s since the visit


# ---- AC2 / AC3 power visit -----------------------------------------------------------------

def visit(p, perc, frame=1000):
    perc.panel = True
    p.power_visit(frame)


def test_power_visit_buys_in_order(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}
    perc.panel = True
    p.sleeps.clear()
    ticks(p, 1)
    buys = [e for e in p.log if e[0] == "tap"]
    want = [CARDS[c] for c in ("Alignment", "Alignment", "Alignment", "Resonance", "Alignment", "Alignment")]
    assert [uv for _, uv in buys[:6]] == want
    assert [uv for _, uv in buys[6:]] == [UI["power_close"]]
    # the panel frame is saved before the first buy tap
    assert p.log[0] == ("frame", "data/support_frames/G/panel_0.0.png")
    # both reads: the first on the tick's frame, the second on a new grab
    frames = [f for f, _ in perc.level_calls]
    assert len(perc.level_calls) == 6 and frames[:3] == [frames[0]] * 3
    assert frames[3] != frames[0] and frames[3:] == [frames[3]] * 3
    assert 0.3 in p.sleeps and p.sleeps.count(0.15) == 6
    assert "power panel -> AAARAA, close (Lv G7 A1 R1, read)" in capsys.readouterr().out
    assert p.power.record()["src"] == "read"


def test_power_visit_closes_until_closed():
    p, g, inj, perc, saver, clock = make(close_after=3)
    perc.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}
    perc.panel = True
    ticks(p, 1)
    assert inj.taps.count(UI["power_close"]) == 3


def test_power_visit_unread_card_is_counted(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [None], "Resonance": [1]}
    perc.panel = True
    ticks(p, 1)
    out = capsys.readouterr().out
    assert "power panel -> AAARAA, close (Lv G7 A1 R1, count)" in out
    assert p.power.record()["src"] == "count"
    # taps made in this visit are counted into the next one
    assert p.power.start_visit({"Growth": 7, "Alignment": None, "Resonance": 1})[0]["Alignment"] == 6      # 1 + 5 A taps


def test_power_visit_two_different_reads_are_unread(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7, 8], "Alignment": [1], "Resonance": [1]}
    perc.panel = True
    ticks(p, 1)
    out = capsys.readouterr().out
    # Growth was never read, so it counts from Lv 1 and Growth is bought first
    assert "power panel -> GGGGGG, close (Lv G1 A1 R1, count)" in out


def test_power_visit_no_cards_found(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.cards = {"Growth": None, "Alignment": None, "Resonance": None}
    perc.panel = True
    ticks(p, 1)
    assert "power panel: cards not found -- closed" in capsys.readouterr().out
    assert not set(inj.taps) & set(CARDS.values())
    assert inj.taps == [UI["power_close"]]


def test_power_visit_nothing_to_buy(capsys, monkeypatch):
    monkeypatch.setattr(sp, "plan_visit", lambda *a, **kw: [])
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}
    perc.panel = True
    ticks(p, 1)
    assert "power panel: nothing to buy -- closed" in capsys.readouterr().out
    assert not set(inj.taps) & set(CARDS.values())


def test_power_visit_prints_maxed_line(capsys, monkeypatch):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}
    real = p.power.start_visit

    def start(read):
        levels, src, lines = real(read)
        return levels, src, lines + ["power card Growth maxed at Lv 8"]

    monkeypatch.setattr(p.power, "start_visit", start)
    perc.panel = True
    ticks(p, 1)
    assert "power card Growth maxed at Lv 8" in capsys.readouterr().out


def test_power_visit_skips_maxed_card(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}
    p.power._maxed.add("Alignment")
    perc.panel = True
    ticks(p, 1)
    assert CARDS["Alignment"] not in inj.taps
    assert "power panel -> RRRRRR" in capsys.readouterr().out


# ---- AC4 score and milestones --------------------------------------------------------------

def test_milestones_with_score(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE)
    perc.scores = [1000]
    ticks(p, 3)
    out = capsys.readouterr().out
    assert "milestone m1 reached at score 1000 (Res7 2, Align7 3, Bubble 2)" in out
    assert "milestone m3 reached at score 1000" in out
    paths = [path for _, path in saver.saved]
    for m in ("m1", "m2", "m3"):
        assert f"data/support_runs/G/{m}_1000.png" in paths
    rec = p.milestones.record()
    assert rec["milestones"]["m2"]["shot"] == "data/support_runs/G/m2_1000.png"
    assert rec["scores_confirmed"] >= 1 and rec["max_score"] == 1000


def test_milestone_without_score_is_na(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 3)
    assert "milestone m1 reached at score ? (Res7 2, Align7 3, Bubble 2)" in capsys.readouterr().out
    assert "data/support_runs/G/m1_na.png" in [path for _, path in saver.saved]
    assert p.milestones.record()["milestones"]["m1"]["score"] is None


def test_single_score_read_is_not_confirmed():
    p, g, inj, perc, saver, clock = make(COMPLETE)
    perc.scores = [1000, 3000, 1000, 3000]                  # never two identical reads in a row
    ticks(p, 4)
    assert p.milestones.record()["scores_confirmed"] == 0


def test_crossing_event(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.scores = [2000]
    ticks(p, 2)
    assert "score crossed 2000 (Res7 0, Align7 0, Bubble 0)" in capsys.readouterr().out
    assert "data/support_runs/G/cross_2000_2000.png" in [path for _, path in saver.saved]
    assert p.milestones.record()["crossings"]["2000"]["shot"] == "data/support_runs/G/cross_2000_2000.png"


def test_covered_window_stores_null_shot(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE, covered=True)
    perc.scores = [2000]
    ticks(p, 3)
    rec = p.milestones.record()
    assert rec["milestones"]["m1"]["shot"] is None
    assert rec["crossings"]["2000"]["shot"] is None
    assert "milestone m1" in capsys.readouterr().out


def test_unconfirmed_board_does_not_feed_milestones():
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 1)                                             # first read only
    assert p.milestones.record()["milestones"]["m1"]["reached"] is False


# ---- AC5 play() ----------------------------------------------------------------------------

class FakeRunPlayer:
    made = []

    def __init__(self, g, inj, saver, game_id=None, tick=0.6, trial=False):
        self.args = (g, inj, saver, game_id, tick, trial)
        self.stats = {"merges": 3, "fails": 1, "support": 2, "complete": True}
        self.last_frame = "LAST"
        FakeRunPlayer.made.append(self)

    def run(self, minutes):
        self.minutes = minutes
        return "game_over"


class FakeCollect(FakeRunPlayer):
    kind = "collect"


class FakePlay(FakeRunPlayer):
    kind = "play"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.milestones = MilestoneTracker()
        self.power = PowerTracker()
        self.power.start_visit({"Growth": 7, "Alignment": 2, "Resonance": 1})


@pytest.fixture
def run_env(monkeypatch, tmp_path):
    FakeRunPlayer.made = []
    saver = RecSaver()
    monkeypatch.setattr(sb, "Saver", lambda g: saver)
    monkeypatch.setattr(sb, "new_game_id", lambda now=None: "sup_T")
    monkeypatch.setattr(sb, "ROUNDS_FILE", str(tmp_path / "data" / "support_rounds.jsonl"))
    monkeypatch.setattr(sp, "CollectPlayer", FakeCollect)
    monkeypatch.setattr(sp, "PlayPlayer", FakePlay)

    def gates(type_, pip):
        monkeypatch.setattr(sb.support, "gate_state", lambda: {"type": type_, "pip": pip})

    return saver, tmp_path / "data" / "support_rounds.jsonl", gates


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("type_,pip,mode,line", [
    (False, False, "collect", "support deck: collect mode (type gate not passed)"),
    (True, False, "trial", "support deck: trial mode (type gate PASS, pip gate FAIL)"),
    (True, True, "play", "support deck: play mode (type gate PASS, pip gate PASS)"),
])
def test_play_modes(run_env, capsys, type_, pip, mode, line):
    saver, path, gates = run_env
    gates(type_, pip)
    g, inj = FakeGrabber(), FakeInjector()
    res = sb.play(g, inj, minutes=1, tick=0.1)
    assert res == "game_over"
    assert line in capsys.readouterr().out
    pl = FakeRunPlayer.made[0]
    assert type(pl) is (FakeCollect if mode == "collect" else FakePlay)
    assert pl.args[:5] == (g, inj, saver, "sup_T", 0.1)
    assert pl.args[5] == (mode == "trial")
    assert ("LAST", "data/support_runs/sup_T/end.png") in saver.saved
    rec = lines(path)[0]
    assert rec["mode"] == mode and rec["result"] == "game_over"
    assert rec["gates"] == {"type": type_, "pip": pip}
    assert rec["stats"] == {"merges": 3, "fails": 1, "support": 2, "complete": True}
    if mode == "collect":
        assert rec["power"] is None
    else:
        assert rec["power"]["levels"] == {"Growth": 7, "Alignment": 2, "Resonance": 1}
        assert rec["power"]["src"] == "read"
    assert sb.play.stats == {"merges": 3, "fails": 1, "support": 2, "complete": True}


def test_play_forced_mode_skips_the_gate(run_env):
    saver, path, gates = run_env
    gates(False, False)
    sb.play(FakeGrabber(), FakeInjector(), mode="play")
    assert type(FakeRunPlayer.made[0]) is FakePlay and FakeRunPlayer.made[0].args[5] is False
    assert lines(path)[0]["mode"] == "play"


def test_play_appends_one_line_per_game(run_env):
    saver, path, gates = run_env
    gates(True, True)
    sb.play(FakeGrabber(), FakeInjector())
    sb.play(FakeGrabber(), FakeInjector())
    assert len(lines(path)) == 2


# ---- AC6 main() ----------------------------------------------------------------------------

@pytest.mark.parametrize("argv,execute,mode", [
    ([], False, None),
    (["--execute"], True, None),
    (["--mode", "auto"], False, None),
    (["--mode", "collect"], False, "collect"),
    (["--mode", "play", "--execute", "--minutes", "5", "--tick", "0.8"], True, "play"),
])
def test_main_dry_run_default_and_forced_mode(monkeypatch, argv, execute, mode):
    import rdom.input.inject as inject
    made, calls = [], []

    class FakeInj:
        def __init__(self, execute=False):
            made.append(execute)

    class FakeG:
        def close(self):
            calls.append("close")

    monkeypatch.setattr(inject, "Injector", FakeInj)
    monkeypatch.setitem(sys.modules, "rdom.capture.live", types.SimpleNamespace(LiveGrabber=FakeG))
    monkeypatch.setattr(sb, "play", lambda g, inj, minutes, tick, mode=None: calls.append((minutes, tick, mode)))
    monkeypatch.setattr(sys, "argv", ["support_bot.py", *argv])
    sb.main()
    assert made == [execute]
    assert calls[0][2] == mode and calls[-1] == "close"
    if "--minutes" in argv:
        assert calls[0][:2] == (5.0, 0.8)


# ---- AC7 -----------------------------------------------------------------------------------

def test_no_loop_modules_imported():
    for name in ("tools.gear_loop", "tools.run_all", "tools.supervisor", "tools.discord_bot",
                 "gear_loop", "run_all", "supervisor", "discord_bot"):
        assert name not in sys.modules
