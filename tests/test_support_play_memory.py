"""PlayPlayer wiring of CellMemory / Burster (rdf02-t6): effective board, bursts, merge verification, log lines."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_players as sp
from rdom.input.inject import cell_uv
from rdom.perception.gear import UI

JUNK = {"type": "junk", "variant": "junk", "pip": 0, "conf": 1.0}
RE3 = ("Resonance", 3)


def rd(v, conf=1.0):
    """One raw read from a (type, pip) value; None -> empty; "junk" -> unreadable."""
    if v == "junk":
        return dict(JUNK)
    if v is None:
        return {"type": "empty", "variant": "empty", "pip": 0, "conf": conf}
    return {"type": v[0], "variant": v[0], "pip": v[1], "conf": conf}


def board(spec):
    """spec {cell: (type, pip) | None | "junk"}; every other cell is Growth 1."""
    return [{"cell": c, **rd(spec.get(c, ("Growth", 1)))} for c in range(1, 16)]


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeGrabber:
    def __init__(self):
        self.n = 0

    def grab(self):
        self.n += 1
        return self.n                                       # every grab differs: none is dropped as a repeat

    def window_moved(self):
        return False

    def unobscured(self):
        return True


class FakeInjector:
    def __init__(self):
        self.taps, self.swipes = [], []

    def tap(self, u, v):
        self.taps.append((u, v))

    def swipe(self, *a, **kw):
        self.swipes.append(a)


class FakeSaver:
    def __init__(self):
        self.bursts = []

    def cells(self, *a, **kw):
        pass

    def frame(self, *a, **kw):
        pass

    def burst(self, game_id, t, cells, grabs, record):
        self.bursts.append(record)
        return ["n"]


class FakePerception:
    """boards: one raw board per read_board_support call (the last one repeats)."""

    def __init__(self, boards):
        self.boards = [board(b) for b in boards]
        self.n = 0
        self.burst_script = {}                              # cell -> list of reads, one per kept frame
        self.burst_pos = {}
        self.sources = []

    def is_game_over(self, f):
        return False

    def tactic_sp1000_card(self, f):
        return None

    def dice_info_panel(self, f):
        return False

    def ui_state(self, f):
        return {"hunt_popup": False, "hunt": False, "power_panel": False, "transcend": False, "hpsp": False}

    def is_battle(self, f):
        return True

    def buffed_cells(self, f):
        return set()

    def board_glare(self, f):
        return False

    def banner_present(self, f):
        return False

    def read_score(self, f):
        return None

    def frames_equal(self, a, b):
        return a == b

    def read_board_support(self, f, pip_source="auto"):
        b = self.boards[min(self.n, len(self.boards) - 1)]
        self.n += 1
        return [dict(d) for d in b]

    def read_cells_support(self, f, cells, pip_source="auto"):
        self.sources.append(pip_source)
        out = []
        for c in cells:
            script = self.burst_script.get(c, [])
            i = self.burst_pos.get(c, 0)
            self.burst_pos[c] = i + 1
            out.append({"cell": c, **(script[i] if i < len(script) else JUNK)})
        return out


@pytest.fixture(autouse=True)
def no_fail_crops(monkeypatch):
    monkeypatch.setattr(sp.collect, "save_fail", lambda f, a, b: None)


def make(boards, trial=False):
    clock = FakeClock()
    perc = FakePerception(boards)
    inj, saver = FakeInjector(), FakeSaver()
    p = sp.PlayPlayer(FakeGrabber(), inj, saver, perc=perc, game_id="G", clock=clock, sleep=clock.sleep,
                      trial=trial)
    return p, inj, perc, saver


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def uses(swipe, cell):
    return cell_uv(cell) in (tuple(swipe[:2]), tuple(swipe[2:4]))


MERGE = {1: RE3, 2: RE3}


def test_hacked_remembered_die_is_merged(capsys):
    seen = {8: RE3}
    hacked = {2: RE3, 8: "junk"}
    p, inj, perc, _ = make([seen, seen, hacked, hacked])
    ticks(p, 4)
    out = capsys.readouterr().out
    assert out.count("cell 8 unreadable -> keep Re3 (last confident read)") == 1
    assert "Re3*" in out
    assert len(inj.swipes) == 1 and uses(inj.swipes[0], 8)
    assert p.stats["mem_ticks"] >= 1


def test_unknown_cell_gets_burst_and_no_action(capsys):
    p, inj, perc, _ = make([{**MERGE, 5: "junk"}])
    ticks(p, 3)
    out = capsys.readouterr().out
    assert "burst cells 5 -> 5=? (6 of 6 grabs)" in out
    assert out.count("cell 5 unreadable -> occupied, unknown") == 1
    assert perc.burst_pos[5] == 6
    assert UI["summon"] not in inj.taps
    assert all(not uses(s, 5) for s in inj.swipes) and inj.swipes
    assert p.stats["bursts"] == 1 and p.stats["burst_hits"] == 0


def test_burst_value_acts_only_after_two_stable_ticks(capsys):
    p, inj, perc, saver = make([{1: RE3, 5: "junk"}, {1: RE3, 5: "junk"}])
    perc.burst_script[5] = [rd(RE3)] * 6
    ticks(p, 1)
    out = capsys.readouterr().out
    assert "burst cells 5 -> 5=Re3 (6 of 6 grabs)" in out
    assert inj.swipes == []                                 # first effective board: not confirmed
    ticks(p, 1)
    assert len(inj.swipes) == 1 and uses(inj.swipes[0], 5)
    assert "Re3*" in capsys.readouterr().out
    assert p.stats["bursts"] == 1 and p.stats["burst_hits"] == 1 and p.stats["mem_ticks"] >= 1
    assert saver.bursts and saver.bursts[0]["result"] == {"5": ["Resonance", 3]}


def test_more_than_three_unreadable_cells_no_action_no_burst():
    p, inj, perc, _ = make([{**MERGE, 3: "junk", 4: "junk", 5: "junk", 6: "junk"}])
    ticks(p, 4)
    assert inj.swipes == [] and inj.taps == []
    assert p.stats["bursts"] == 0 and perc.sources == []
    p2, inj2, perc2, _ = make([{**MERGE, 3: "junk", 4: "junk", 5: "junk"}])
    ticks(p2, 2)
    assert p2.stats["bursts"] == 1 and len(inj2.swipes) == 1


def test_refused_merge_bans_pair_and_keeps_memory(capsys):
    p, inj, perc, _ = make([MERGE])
    ticks(p, 3)
    out = capsys.readouterr().out
    assert "merge 1->2 had no effect -> banned until those dice change" in out
    assert p.stats["fails"] == 1
    assert p.memory.memory(1) == RE3 and p.memory.memory(2) == RE3
    ticks(p, 2)
    assert [s for s in inj.swipes if s[:2] == cell_uv(1)] == inj.swipes[:1]   # 1->2 banned, not repeated


def test_burst_external_event_forgets_cell_resolved_earlier_in_burst():
    AD4, BU3, BU5 = ("Adjust", 4), ("Bubble", 3), ("Bubble", 5)
    seen = {1: AD4, 5: AD4, 6: BU3}
    p, inj, perc, _ = make([seen, seen, {**seen, 5: "junk", 6: "junk"}])
    perc.burst_script[5] = [rd(AD4)] * 6
    perc.burst_script[6] = [rd(BU5)] * 6                    # refresh burst: cell 6 changed, 5 was resolved first
    ticks(p, 2)
    done = len(inj.swipes)                                  # cell 1 and 5 merge while both are readable
    ticks(p, 1)
    assert p.stats["bursts"] == 1 and p.memory.memory(5) is None and p.memory.memory(6) == BU5
    assert p._prev_sig[4] == ("junk", 0)                    # this tick's effective board must not keep the old die
    assert all(not uses(s, 5) for s in inj.swipes[done:])


def spy_merged(p):
    calls = []
    orig = p.memory.merged
    p.memory.merged = lambda fr, to: (calls.append((fr, to)), orig(fr, to))[1]
    return calls


def test_remembered_from_cell_unreadable_then_late_effect(capsys):
    hacked = {**MERGE, 1: "junk"}
    p, inj, perc, _ = make([MERGE, MERGE, hacked, {1: None, 2: RE3}, {1: None, 2: RE3}])
    calls = spy_merged(p)
    ticks(p, 2)
    assert len(inj.swipes) == 1
    ticks(p, 1)                                             # from-cell unreadable: undecided
    assert p.stats["fails"] == 0 and len(inj.swipes) == 1 and calls == []
    ticks(p, 2)                                             # from-cell confidently empty: effect
    out = capsys.readouterr().out
    assert calls == [(1, 2)]
    assert "had no effect" not in out and "board changed without our action" not in out
    assert p.stats["fails"] == 0 and p.stats["forgets"] == 0


def test_unreadable_for_three_verification_ticks_counts_as_effect(capsys):
    hacked = {**MERGE, 1: "junk"}
    p, inj, perc, _ = make([MERGE, MERGE, hacked])
    calls = spy_merged(p)
    ticks(p, 4)
    assert calls == [] and len(inj.swipes) == 1             # two undecided ticks so far
    ticks(p, 1)                                             # third undecided tick
    assert calls == [(1, 2)]
    assert "had no effect" not in capsys.readouterr().out
    assert p.stats["fails"] == 0 and len(inj.swipes) == 1


def test_external_change_logs_and_forgets(capsys):
    a = {4: ("Light", 1), 8: ("Bubble", 1)}
    hacked = {4: ("Light", 1), 8: "junk"}
    changed = {4: ("Switch", 1), 8: "junk"}
    p, inj, perc, _ = make([a, a, hacked, changed, changed])
    ticks(p, 5)
    out = capsys.readouterr().out
    assert "board changed without our action at 4 -> forget remembered 8" in out
    assert "cell 8 unreadable -> occupied, unknown" in out
    assert p.stats["forgets"] == 1 and p.memory.memory(8) is None


def test_fmt_board_marks_memory_and_burst_tokens():
    b = [{"type": "Resonance", "pip": 3, "src": "memory"}, {"type": "Resonance", "pip": 3, "src": "burst"},
         {"type": "Resonance", "pip": 3, "src": "read"}, {"type": "junk", "pip": 0, "src": "unknown"},
         {"type": "empty", "pip": 0}]
    assert sp.fmt_board(b) == "Re3* Re3* Re3 ju0 ..."


@pytest.mark.parametrize("trial,src", [(True, "gear"), (False, "auto")])
def test_burst_reads_use_pip_source(trial, src):
    p, inj, perc, _ = make([{5: "junk"}], trial=trial)
    ticks(p, 1)
    assert perc.sources and set(perc.sources) == {src}
