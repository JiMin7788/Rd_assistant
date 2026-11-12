"""rdT16 sevens data mode: switch file, gear/support sevens plans, extra pip 6/7 crops, stats.
All input is faked; nothing is written under data/."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
import support_bot as sb
import support_players as sp
import rdom.perception.gear as gp
import rdom.policy.gear as pg
from rdom.perception import collect, support
from rdom.perception.gear import UI
from rdom.policy import data_mode
from rdom.policy.support import plan_support
from test_support_play_player import FakeClock, FakeGrabber, FakeInjector, FakePerception

ROOT = Path(__file__).resolve().parents[1]
GT = {"G": "Gear", "B": "Bubble", "A": "Adjust", "R": "Growth", "D": "Doom", "J": "Joker", "X": "Bomb"}
ST = {"R": "Resonance", "L": "Alignment", "B": "Bubble", "A": "Adjust", "G": "Growth", "J": "Joker", "X": "Bomb"}


def _die(cell, tok, types):
    if tok == ".":
        return {"cell": cell, "type": "empty", "variant": "empty", "pip": 0}
    t = types[tok[0]]
    pip = 0 if tok == "X" else int(tok[1])
    return {"cell": cell, "type": t, "variant": t, "pip": pip}


def gear_board(cells, filler="R1"):
    """{cell: token}; every other cell is a Growth 1 (never merged, never a supporter pick)."""
    return [_die(c, cells.get(c, filler), GT) for c in range(1, 16)]


def sup_board(cells, filler="G1"):
    return [_die(c, cells.get(c, filler), ST) for c in range(1, 16)]


@pytest.fixture(autouse=True)
def doom_keep(monkeypatch):
    monkeypatch.setattr(pg, "KEEP", {"Bubble": (1, 3, 1)})


def sevens_on(monkeypatch, tmp_path):
    p = tmp_path / "data_mode.toml"
    p.write_text("sevens = true\n", encoding="utf-8")
    monkeypatch.setattr(data_mode, "FILE", str(p))


# ---- AC1 switch ---------------------------------------------------------------------------------

def test_switch_missing_false_and_bad_file_are_off(tmp_path):
    assert data_mode.sevens() is False                     # conftest: FILE points at a missing file
    assert data_mode.sevens(str(tmp_path / "nope.toml")) is False
    for text in ("sevens = false\n", "sevens = 1\n", "sevens = [\n", "other = true\n"):
        p = tmp_path / "x.toml"
        p.write_text(text, encoding="utf-8")
        assert data_mode.sevens(str(p)) is False, text


def test_switch_on_and_repo_file_is_on(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text("sevens = true\n", encoding="utf-8")
    assert data_mode.sevens(str(p)) is True
    assert data_mode.sevens(str(ROOT / "config" / "data_mode.toml")) is True


# ---- AC2 gear sevens plan -----------------------------------------------------------------------

def test_gear_highest_pip_pair_first():
    b = gear_board({1: "G2", 2: "G2", 3: "B3", 4: "B3", 5: "B1", 8: "G6", 9: "G6"})
    a = pg.plan_next(b, sevens=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {8, 9}
    # before 초월 the normal plan never merges gears
    assert pg.plan_next(b) != a


def test_gear_pip7_never_merged():
    b = gear_board({1: "G7", 2: "G7", 3: "A7", 4: "D7", 5: "D7"})
    a = pg.plan_next(b, transcended=True, sevens=True)
    assert a == {"op": "wait", "why": "no move"}
    j = gear_board({1: "J7", 2: "G7"})
    assert pg.plan_next(j, sevens=True)["op"] == "wait"   # no Joker copy onto a 7 either


def test_gear_supporter_drags_a_7_only_when_ready():
    b = gear_board({1: "G2", 2: "G2", 3: "G7"})
    assert pg.plan_next(b, support_ready=True, sevens=True) == {"op": "support", "from": 3}
    a = pg.plan_next(b, support_ready=False, sevens=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {1, 2}


def test_gear_drop_preference():
    assert pg.plan_next(gear_board({1: "G7", 9: "D7"}), support_ready=True, sevens=True)["from"] == 9
    b = gear_board({2: "D7", 4: "B7", 5: "B7", 6: "B1", 10: "G7", 11: "G7", 12: "G7"})
    assert pg.plan_next(b, support_ready=True, sevens=True)["from"] == 4      # Bubble has 2 sevens
    assert pg.plan_next(gear_board({1: "G7", 2: "G7", 3: "G7"}), support_ready=True,
                        sevens=True)["from"] == 1


def test_gear_no_complete_wait_and_summon_and_bombs():
    final = [_die(i, t, GT) for i, t in enumerate(
        "G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 G2 G2".split(), 1)]
    assert pg.evaluate(final)["complete"]
    a = pg.plan_next(final, sevens=True)
    assert a["op"] == "merge" and final[a["from"] - 1]["pip"] == 3
    assert pg.plan_next(gear_board({1: "."}), sevens=True) == {"op": "summon"}
    bombs = gear_board({1: "X", 2: "X", 3: "G7"})
    assert pg.plan_next(bombs, support_ready=True, sevens=True) == {"op": "merge", "from": 1, "to": 2}


def test_gear_banned_pair_kept_and_old_pool_used():
    b = gear_board({1: "G6", 2: "G6", 3: "B3", 4: "B3", 5: "B1"})
    a = pg.plan_next(b, sevens=True, banned={(1, 2), (2, 1)})
    assert a["op"] == "merge" and {a["from"], a["to"]} == {3, 4}
    assert pg.plan_next(gear_board({5: "A4"}), support_ready=True, sevens=True) == {"op": "support", "from": 5}


def test_gear_switch_off_is_the_old_plan():
    for cells in ({1: "G2", 2: "G2", 3: "G7"}, {1: "G6", 2: "G6", 3: "B1"}, {1: "X", 2: "A1"}, {5: "A4"}):
        b = gear_board(cells)
        for kw in ({}, {"transcended": True}, {"support_ready": True}):
            assert pg.plan_next(b, **kw) == pg.plan_next(b, sevens=False, **kw)


# ---- AC3 support sevens plan --------------------------------------------------------------------

def test_support_highest_pip_beats_surplus_bubble_rule():
    b = sup_board({1: "B2", 2: "B2", 3: "B3", 4: "B4", 6: "R5", 7: "R5"})
    a = plan_support(b, sevens=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {6, 7}
    assert plan_support(b)["op"] == "merge" and plan_support(b) != a       # old: must consume a Bubble


def test_support_pip7_never_merged():
    b = sup_board({1: "R7", 2: "R7", 3: "A7", 4: "L7", 5: "J7"})
    assert plan_support(b, sevens=True) == {"op": "wait", "why": "no move"}


def test_support_supporter_drags_a_7_only_when_ready():
    b = sup_board({1: "R3", 2: "R3", 5: "R7"})
    assert plan_support(b, support_ready=True, sevens=True) == {"op": "support", "from": 5}
    a = plan_support(b, support_ready=False, sevens=True)
    assert a == {"op": "merge", "from": 1, "to": 2} or a == {"op": "merge", "from": 2, "to": 1}


def test_support_drop_preference():
    assert plan_support(sup_board({1: "R7", 2: "R7", 9: "A7"}), support_ready=True, sevens=True)["from"] == 9
    assert plan_support(sup_board({1: "L7", 4: "R7", 5: "R7"}), support_ready=True, sevens=True)["from"] == 4


def test_support_no_completion_wait_and_old_pool():
    complete = sup_board({1: "R6", 2: "R6", 3: "L6", 4: "L6", 5: "L6", 6: "B2", 7: "B3"})
    assert plan_support(complete, sevens=True)["op"] == "merge"
    done = [dict(d, pip=7) if d["cell"] <= 5 else d for d in complete]
    assert plan_support(done, sevens=True) == {"op": "wait", "why": "no move"}
    assert plan_support(done) == {"op": "wait", "why": "complete"}
    assert plan_support(sup_board({1: "A4"}), support_ready=True, sevens=True) == {"op": "support", "from": 1}
    assert plan_support(sup_board({1: "X", 2: "A1", 3: "R7"}), support_ready=True,
                        sevens=True) == {"op": "merge", "from": 1, "to": 2}


def test_support_switch_off_is_the_old_plan():
    for cells in ({1: "R3", 2: "R3", 5: "R7"}, {1: "B2", 2: "B2", 3: "B3", 4: "B4", 6: "R5", 7: "R5"}, {1: "A4"}):
        b = sup_board(cells)
        for kw in ({}, {"support_ready": True}, {"clone_alert": True}):
            assert plan_support(b, **kw) == plan_support(b, sevens=False, **kw)


# ---- AC4 extra crops: HiWatch, savers ----------------------------------------------------------

def test_hiwatch_new_6_or_7_once_per_cell_per_5s():
    w = collect.HiWatch()
    assert collect.HI_EVERY == 5.0
    assert w.update(gear_board({3: "G6"}), 100.0) == ([3], 0)
    assert w.update(gear_board({3: "G6"}), 101.0) == ([], 0)            # same die: nothing
    assert w.update(gear_board({3: "D7"}), 102.0) == ([], 1)            # new 7 counted, crop throttled
    assert w.update(gear_board({3: "G6"}), 105.0) == ([3], 0)           # 5 s after the last crop
    assert w.update(gear_board({3: "G6", 4: "B7", 5: "G5"}), 105.5) == ([4], 1)


def test_hiwatch_junk_keeps_the_last_read_and_empty_is_ignored():
    w = collect.HiWatch()
    w.update(gear_board({3: "G7"}), 0.0)
    junk = gear_board({3: "G7"})
    junk[2].update(type="junk", pip=0)
    assert w.update(junk, 10.0) == ([], 0)
    assert w.update(gear_board({3: "G7"}), 20.0) == ([], 0)             # flicker through junk: no new die
    assert w.update(gear_board({3: "."}), 30.0) == ([], 0)


def test_save_cells_writes_only_given_cells(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(collect, "RAW", str(tmp_path / "raw"))
    monkeypatch.setattr(collect, "LABELS", str(tmp_path / "labels.jsonl"))
    f = np.zeros((1280, 720, 3), np.uint8)
    b = gear_board({3: "G6", 4: "B7"})
    assert collect.save_cells(f, b, [3, 4]) == 2
    assert len(list((tmp_path / "raw").glob("*.png"))) == 2
    assert collect.save_cells(f, b, [3], unobscured=False) == 0
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path / "sup"))
    assert collect.save_support_cells(f, "g", 1.0, True, cells=[7]) == 1
    assert [p.name for p in (tmp_path / "sup" / "_raw").glob("*.png")] == ["g_1.0_07.png"]
    assert collect.save_support_cells(f, "g", 1.0, False, cells=[7]) == 0


# ---- AC4 gear_bot.play: stats, crops, drops, summary --------------------------------------------

def load_gear_bot():
    spec = importlib.util.spec_from_file_location("gear_bot_sevens_under_test",
                                                  os.path.join(ROOT, "tools", "gear_bot.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class GearRun:
    """Fake grabber + injector + clock; `boards` = one board per loop, then the window 'moves'."""
    execute = False
    last_gesture_ok = True

    def __init__(self, bot, monkeypatch, boards):
        self.bot, self.boards, self.loop, self.clock = bot, boards, 0, 1000.0
        self.swipes, self.saved, self.plans = [], [], []
        monkeypatch.setattr(bot.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(bot.time, "sleep", self.sleep)
        monkeypatch.setattr(bot, "is_game_over", lambda f: False)
        monkeypatch.setattr(bot, "is_battle", lambda f: True)
        monkeypatch.setattr(bot, "banner_present", lambda f: False)
        monkeypatch.setattr(bot, "buffed_cells", lambda f: set())
        monkeypatch.setattr(bot, "ui_state", lambda f: dict(hunt_popup=False, transcend=False,
                                                             power_panel=False, hpsp=False, hunt=False))
        monkeypatch.setattr(bot, "read_board", lambda f: [dict(d) for d in self.boards[self.loop - 1]])
        real = bot.plan_next
        monkeypatch.setattr(bot, "plan_next", lambda b, **k: (self.plans.append(k["sevens"]), real(b, **k))[1])
        monkeypatch.setattr(support, "detect_support_deck", lambda f, **k: False)
        monkeypatch.setattr(gp, "tactic_sp1000_card", lambda f: None)
        monkeypatch.setattr(gp, "detect_deck", lambda f: None)
        monkeypatch.setattr(gp, "set_deck", lambda name: None)
        monkeypatch.setattr(pg, "load_deck", lambda *a, **k: pg.KEEP)
        monkeypatch.setattr(collect, "maybe_save", lambda *a, **k: None)
        monkeypatch.setattr(collect, "save_fail", lambda *a, **k: None)
        monkeypatch.setattr(collect, "save_cells", self.save_cells)

    def window_moved(self):
        self.loop += 1
        return self.loop > len(self.boards)

    def grab(self):
        return object()

    def unobscured(self):
        return True

    def tap(self, *uv):
        pass

    def swipe(self, *a, **k):
        self.swipes.append((a, a[-2:] == tuple(UI["support"])))

    def sleep(self, s):
        self.clock += s

    def save_cells(self, f, b, cells, unobscured=True):
        self.saved.append(list(cells))
        return len(cells)


def test_gear_play_sevens_counts_crops_drops_and_summary(monkeypatch, tmp_path, capsys):
    sevens_on(monkeypatch, tmp_path)
    bot = load_gear_bot()
    b0 = gear_board({1: "G2", 2: "G2", 3: "G6"})
    b1 = gear_board({1: ".", 2: "D7", 3: "G6"})
    b1[0] = dict(b1[0], type="Growth", variant="Growth", pip=1)
    r = GearRun(bot, monkeypatch, [b0, b0, b1, b1, b1])
    assert bot.play(r, r, minutes=10) == "moved"
    out = capsys.readouterr().out
    st = bot.play.stats
    assert out.count("data mode: sevens") == 1
    assert r.saved == [[3], [2]]                                        # G6 at loop 2, D7 at loop 4
    assert st["sevens"] == 1 and st["hi_crops"] == 2
    assert st["merges"] == 1 and st["support"] == 1 and st["drops"] == 1
    assert r.swipes[-1][1] is True                                      # the 7 went onto the supporter
    assert set(r.plans) == {True}
    assert "gear result: moved (merges 1, fails 0, support 1, sevens 1, drops 1, hi_crops 2)" in out


def test_gear_play_switch_missing_is_off(monkeypatch, capsys):
    bot = load_gear_bot()
    b0 = gear_board({1: "G2", 2: "G2", 3: "G6"})
    r = GearRun(bot, monkeypatch, [b0, b0, b0])
    bot.play(r, r, minutes=10)
    out = capsys.readouterr().out
    assert "data mode" not in out and "gear result" not in out
    assert set(r.plans) == {False} and r.saved == []
    assert set(bot.play.stats) == {"merges", "fails", "support", "complete"}


# ---- AC4 support PlayPlayer: stats, crops, drops; support_bot summary ---------------------------

class CountSaver:
    def __init__(self):
        self.cell_calls = []

    def burst(self, *a, **kw):
        return None

    def cells(self, f, game_id, t, **kw):
        if "cells" in kw:
            self.cell_calls.append(list(kw["cells"]))
            return len(kw["cells"])
        return 15

    def frame(self, *a, **kw):
        return None


def make_player(spec):
    clock = FakeClock()
    perc = FakePerception(spec)
    g, inj, saver = FakeGrabber(), FakeInjector(perc.on_tap), CountSaver()
    p = sp.PlayPlayer(g, inj, saver, perc=perc, game_id="G", clock=clock, sleep=clock.sleep, tick=0.6)
    return p, inj, perc, saver, clock


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def test_play_player_sevens_drop_crops_and_throttle(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sp.collect, "save_fail", lambda *a: None)
    sevens_on(monkeypatch, tmp_path)
    p, inj, perc, saver, clock = make_player({1: ("Resonance", 3), 2: ("Resonance", 3), 5: ("Resonance", 7)})
    assert p.sevens and "data mode: sevens" in capsys.readouterr().out
    ticks(p, 2)                                                         # tick 2: stable -> crop + drop
    assert saver.cell_calls == [[5]]
    assert inj.swipes[-1][-2:] == tuple(UI["support"])
    assert p.stats["drops"] == 1 and p.stats["sevens"] == 1
    perc.board[4].update(type="Adjust", variant="Adjust")              # another 7 at cell 5 within 5 s
    ticks(p, 2)
    assert p.stats["sevens"] == 2 and saver.cell_calls == [[5]]         # counted, crop throttled
    clock.t += 5.0
    perc.board[4].update(type="Alignment", variant="Alignment", pip=6)
    ticks(p, 2)
    assert saver.cell_calls == [[5], [5]] and p.stats["hi_crops"] == 2
    assert p.stats["drops"] == 1                                        # supporter on cooldown


def test_play_player_switch_missing_is_off(capsys):
    p, inj, perc, saver, clock = make_player({5: ("Resonance", 7)})
    ticks(p, 3)
    assert not p.sevens and "sevens" not in p.stats and saver.cell_calls == []
    assert "data mode" not in capsys.readouterr().out


class SevensRunPlayer:
    def __init__(self, g, inj, saver, game_id=None, tick=0.6, trial=False):
        self.stats = {"merges": 3, "fails": 0, "support": 2, "complete": False,
                      "sevens": 4, "drops": 2, "hi_crops": 5}
        self.last_frame = "LAST"

    def run(self, minutes):
        return "game_over"


def test_support_result_line_has_sevens_stats(monkeypatch, tmp_path, capsys):
    class NoSaver:
        def frame(self, *a):
            return None
    monkeypatch.setattr(sb, "Saver", lambda g: NoSaver())
    monkeypatch.setattr(sb, "new_game_id", lambda now=None: "sup_T")
    monkeypatch.setattr(sb, "ROUNDS_FILE", str(tmp_path / "rounds.jsonl"))
    monkeypatch.setattr(sp.Perception, "read_score", lambda self, f: None)
    monkeypatch.setattr(sp, "PlayPlayer", SevensRunPlayer)
    monkeypatch.setattr(sb.support, "gate_state", lambda: {"type": True, "pip": True})
    sb.play(FakeGrabber(), FakeInjector(), minutes=1)
    out = capsys.readouterr().out
    assert "support result: game_over (max score 0, last frame -, sevens 4, drops 2, hi_crops 5)" in out
    assert sb.play.stats["sevens"] == 4
