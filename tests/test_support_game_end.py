"""Game end (rdf03-t2): confirmed game over, 'clear' at 5000, judge eligibility.
Fakes only; the gear_loop guard is tested in test_gear_loop_result.py."""
import datetime
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_bot as sb
import support_players as sp
from test_support_play_player import (FakeClock, FakeGrabber, FakeInjector, FakePerception,
                                      MERGE)
from test_support_judge import five, rec, sj

ROOT = Path(__file__).resolve().parents[1]


class GoPerception(FakePerception):
    def __init__(self):
        super().__init__(MERGE)
        self.over = False
        self.battle = True

    def is_game_over(self, f):
        return self.over

    def is_battle(self, f):
        return self.battle


class PathSaver:
    def __init__(self, ok=True):
        self.frames, self.ok = [], ok

    def cells(self, *a, **kw):
        pass

    def burst(self, *a, **kw):
        pass

    def frame(self, frame, path):
        self.frames.append(path)
        return path if self.ok else None


def make(ok=True):
    clock = FakeClock()
    perc, saver, inj = GoPerception(), PathSaver(ok), FakeInjector()
    p = sp.PlayPlayer(FakeGrabber(), inj, saver, perc=perc, game_id="G", clock=clock,
                      sleep=clock.sleep, tick=0.6)
    return p, inj, perc, saver, clock


def go_frames(saver):
    return [x for x in saver.frames if "gameover_" in x]


def test_lookalike_with_battle_ui_does_not_stop(capsys):
    # H2 06:39: one game-over-coloured frame while the battle UI is still up
    p, inj, perc, saver, clock = make()
    p.tick()
    inj.taps.clear()
    perc.over = True
    assert p.tick() is None
    perc.over = False
    assert p.tick() is None
    out = capsys.readouterr().out
    assert "game over\n" not in out and "hunt" not in out
    assert out.count("game-over look-alike ignored (battle screen visible)") == 1
    assert all(t != sp.gear.UI["hunt"] for t in inj.taps)
    assert go_frames(saver) == ["data/support_runs/G/gameover_lookalike_0.0.png"]


def test_lookalike_log_once_per_10s_and_save_cap(capsys):
    p, inj, perc, saver, clock = make()
    p.tick()
    perc.over = True
    for _ in range(100):                    # 100 ticks of 0.6 s = 60 s
        clock.sleep(0.6)
        assert p.tick() is None
    out = capsys.readouterr().out
    assert out.count("look-alike ignored") == 6
    assert len(go_frames(saver)) == 3


def test_lookalike_none_save_does_not_count():
    p, inj, perc, saver, clock = make(ok=False)
    p.tick()
    perc.over = True
    for _ in range(10):
        clock.sleep(11)
        p.tick()
    assert len(go_frames(saver)) == 10
    saver.ok = True
    clock.sleep(11)
    p.tick()
    assert len(go_frames(saver)) == 11


def test_result_screen_two_ticks_stops(capsys):
    p, inj, perc, saver, clock = make()
    p.tick()
    perc.over, perc.battle = True, False
    assert p.tick() is None                 # pending
    assert p.tick() == "game_over"
    assert capsys.readouterr().out.count("game over") == 1


def test_pending_tick_skips_board_action():
    p, inj, perc, saver, clock = make()
    p.tick()
    inj.taps.clear()
    perc.over, perc.battle = True, False
    p.tick()
    assert inj.taps == [] and inj.swipes == []


def test_result_once_is_not_confirmed(capsys):
    p, inj, perc, saver, clock = make()
    p.tick()
    perc.over, perc.battle = True, False
    assert p.tick() is None
    perc.over, perc.battle = False, True
    clock.sleep(0.6)
    assert p.tick() is None
    out = capsys.readouterr().out
    assert out.count("game-over screen seen once -- not confirmed") == 1
    assert go_frames(saver) == ["data/support_runs/G/gameover_once_0.6.png"]
    perc.over, perc.battle = True, False        # counter was reset: one tick is pending again
    assert p.tick() is None
    assert p.tick() == "game_over"


def test_seen_once_saves_the_result_like_frame():
    # AI-NOTE: FakeGrabber returns the grab count, so each frame object is distinct and traceable
    p, inj, perc, saver, clock = make()
    frames = []
    saver.frame = lambda frame, path: frames.append((frame, path)) or path
    p.tick()                                    # frame 1: battle
    perc.over, perc.battle = True, False
    p.tick()                                    # frame 2: result-like, pending
    perc.over, perc.battle = False, True
    clock.sleep(0.6)
    p.tick()                                    # frame 3: battle again -> "seen once"
    assert [x for x in frames if "gameover_once" in x[1]] == [(2, "data/support_runs/G/gameover_once_0.6.png")]


def test_seen_once_save_cap():
    p, inj, perc, saver, clock = make()
    p.tick()
    for _ in range(5):
        perc.over, perc.battle = True, False
        p.tick()
        perc.over, perc.battle = False, True
        p.tick()
    assert len([x for x in saver.frames if "gameover_once" in x]) == 3


def test_run_returns_game_over_after_confirmed_result():
    p, inj, perc, saver, clock = make()
    perc.over, perc.battle = True, False
    assert p.run(1) == "game_over"


# ---- support_bot.play(): clear / game_over decision ----

class RecSaver:
    def frame(self, frame, path):
        return path


class EndPlayer:
    last_frame = "LAST"

    def __init__(self, g, inj, saver, game_id=None, tick=None, trial=False):
        self.stats = {"merges": 0, "fails": 0, "support": 0, "complete": False}
        self.milestones = sb.MilestoneTracker()
        self.power = None
        EndPlayer.made = self

    def run(self, minutes):
        return EndPlayer.res


@pytest.fixture
def env(monkeypatch, tmp_path):
    EndPlayer.res, EndPlayer.last_frame = "game_over", "LAST"
    path = tmp_path / "rounds.jsonl"
    monkeypatch.setattr(sb, "Saver", lambda g: RecSaver())
    monkeypatch.setattr(sb, "new_game_id", lambda now=None: "sup_T")
    monkeypatch.setattr(sb, "ROUNDS_FILE", str(path))
    monkeypatch.setattr(sb.support, "gate_state", lambda: {"type": True, "pip": True})
    monkeypatch.setattr(sp, "PlayPlayer", EndPlayer)

    def go(max_score, final, res="game_over"):
        EndPlayer.res = res
        monkeypatch.setattr(sp.Perception, "read_score", lambda self, f: final)
        orig = EndPlayer.__init__

        def init(self, *a, **kw):
            orig(self, *a, **kw)
            self.milestones.max_score = max_score
        monkeypatch.setattr(EndPlayer, "__init__", init)
        r = sb.play(FakeGrabber(), FakeInjector(), minutes=1)
        return r, json.loads(path.read_text(encoding="utf-8").splitlines()[-1])

    return go


def test_clear_by_max_score(env, capsys):
    r, record = env(5000, None)
    assert r == "clear" and record["result"] == "clear"
    assert "final_score" in record and record["final_score"] is None
    assert "support result: clear (max score 5000, last frame -)" in capsys.readouterr().out


def test_clear_by_final_score_only(env, capsys):
    r, record = env(4630, 5000)
    assert r == "clear" and record["final_score"] == 5000
    assert "support result: clear (max score 4630, last frame 5000)" in capsys.readouterr().out


def test_game_over_below_5000(env, capsys):
    r, record = env(4630, 4800)
    assert r == "game_over" and record["result"] == "game_over" and record["final_score"] == 4800
    assert "support result: game_over (max score 4630, last frame 4800)" in capsys.readouterr().out


def test_game_over_final_score_none(env):
    r, record = env(1200, None)
    assert r == "game_over" and "final_score" in record and record["final_score"] is None


def test_other_results_stay(env):
    r, record = env(5200, 5200, res="timeout")
    assert r == "timeout" and "final_score" in record and record["final_score"] is None


def test_clear_constant():
    assert sb.CLEAR_SCORE == 5000


def test_build_record_final_score_keyword():
    ms = {"max_score": 10, "scores_confirmed": 1, "milestones": {}, "crossings": []}
    now = datetime.datetime(2026, 10, 30)
    r = sb.build_record("g", now, now, "clear", "play", {}, ms, None, {}, final_score=5000)
    assert r["final_score"] == 5000


def test_build_record_final_score_defaults_to_null():
    ms = {"max_score": 10, "scores_confirmed": 1, "milestones": {}, "crossings": []}
    now = datetime.datetime(2026, 10, 30)
    r = sb.build_record("g", now, now, "clear", "play", {}, ms, None, {})
    assert "final_score" in r and r["final_score"] is None


# ---- judge ----

def test_judge_counts_clear_as_eligible():
    assert sj._exclusion(rec(result="clear")) is None
    assert sj._exclusion(rec(result="moved")) == "abnormal"
    recs = [rec("c0", result="clear")] + five(5)[:4]
    lines, code = sj.judge(recs)
    assert code == 0 and not lines[0].startswith("제외")
    assert any(l.startswith("1. c0") for l in lines)


# gear_loop's after-battle handling is tested behaviourally in tests/test_gear_loop_result.py
