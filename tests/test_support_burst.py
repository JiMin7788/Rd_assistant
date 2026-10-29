import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_bot as sb
import support_players as sp
from rdom.perception import collect


def frame(seed=0):
    return np.random.default_rng(seed).integers(0, 255, (1280, 720, 3), dtype=np.uint8)


RECORD = {"game": "g", "t": 5.0, "cells": [3, 4], "grabs": 5, "kept": 2, "reads": {}, "result": {},
          "memory": {}, "buffed": [], "glare": False}


def test_save_burst_files_and_line(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path))
    names = collect.save_burst("g", 5.0, [3, 4], [frame(1), frame(2)], True, RECORD)
    assert names == ["g_5.0_03_0", "g_5.0_04_0", "g_5.0_03_1", "g_5.0_04_1"]
    for n in names:
        assert cv2.imread(str(tmp_path / "_burst" / "_raw" / (n + ".png"))).shape[:2] == (72, 72)
        assert cv2.imread(str(tmp_path / "_burst" / "_hires" / (n + ".png"))).shape[:2] == (128, 128)
    lines = (tmp_path / "_burst" / "bursts.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert set(row) == set(RECORD) | {"names"} and row["names"] == names


def test_save_burst_covered(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(collect, "_covered_logged", [-1e9])
    assert collect.save_burst("g", 5.0, [3], [frame()], False, RECORD) is None
    assert "frame not saved: game window covered" in capsys.readouterr().out
    assert not (tmp_path / "s").exists()


class G:
    def __init__(self, frames=(), clear=True):
        self.frames, self.clear = list(frames), clear

    def grab(self):
        return self.frames.pop(0)

    def unobscured(self):
        return self.clear


class Inj:
    def __init__(self):
        self.calls = []

    def tap(self, *a):
        self.calls.append(a)

    def swipe(self, *a, **kw):
        self.calls.append(a)


class Perc:
    """Frames are ints; negative = not a battle frame."""

    def __init__(self):
        self.read_calls = []

    def is_battle(self, f):
        return f >= 0

    def frames_equal(self, a, b):
        return a == b

    def read_cells_support(self, f, cells, pip_source="auto"):
        self.read_calls.append((f, list(cells), pip_source))
        return [{"cell": c, "type": "Growth", "variant": "Growth", "pip": 1, "conf": 0.5 + f / 100}
                for c in [3, 9]]                # always returns an extra cell 9


class Saver:
    def __init__(self, results=None):
        self.results, self.calls = results, []

    def burst(self, *a):
        self.calls.append(a)
        return self.results.pop(0) if self.results else ["n"]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Player:
    def __init__(self, frames=(), saver=None):
        self.g, self.inj, self.saver = G(frames), Inj(), saver or Saver()
        self.perc, self.clock = Perc(), Clock()
        self.slept = []
        self.sleep = self.slept.append


class Mem:
    def __init__(self, states):
        self.states = states

    def state(self, c):
        return self.states.get(c, "readable")


def test_run_drops_duplicate_and_nonbattle():
    p = Player([1, 1, -1, 2, 3])        # dup of tick frame, not battle, then two new
    b = sp.Burster(p)
    kept, reads, grabs = b.run(1, [3], "gear")
    assert kept == [1, 2, 3] and grabs == 5
    assert p.slept == [0.08] * 5
    assert list(reads) == [3] and [d["conf"] for d in reads[3]] == [0.51, 0.52, 0.53]
    assert p.perc.read_calls == [(1, [3], "gear"), (2, [3], "gear"), (3, [3], "gear")]
    assert p.inj.calls == []


def test_due_timing_rules():
    b = sp.Burster(Player())
    mem = Mem({3: "unknown", 4: "remembered", 5: "remembered"})
    assert b.due(10.0, [3, 4], mem) == [3, 4]            # remembered, never burst -> due at once
    assert b.due(10.0, [], mem) == []
    assert b.due(10.0, [3, 4, 5, 6], mem) == []          # more than MAX_JUNK
    b.done(10.0, [3, 4], {3: None, 4: None}, {3: [], 4: []}, 0.9)
    assert b.due(12.9, [3, 4, 5], mem) == []             # < 3 s since the last burst
    assert b.due(13.1, [3, 4, 5], mem) == [3, 5]         # 4 burst 3.1 s ago -> not yet
    assert b.due(25.1, [3, 4, 5], mem) == [3, 4, 5]


def test_due_backoff_and_reset():
    b = sp.Burster(Player())
    mem = Mem({3: "unknown"})
    junk = {3: [{"type": "junk", "pip": 0, "conf": 0.2}]}
    for i in range(3):
        b.done(10.0 * i, [3], {3: None}, junk, 0.9)
    assert b.fails[3] == 3
    assert b.due(20.0 + 3.1, [3], mem) == []
    assert b.due(20.0 + 15.1, [3], mem) == [3]
    b.done(40.0, [3], {3: ("Growth", 1)}, junk, 0.9)       # accepted value
    assert b.fails[3] == 0
    b.done(50.0, [3], {3: None}, junk, 0.9)
    b.done(60.0, [3], {3: None}, junk, 0.9)
    b.done(70.0, [3], {3: None}, junk, 0.9)
    assert b.fails[3] == 3
    b.done(80.0, [3], {3: None}, {3: [{"type": "Growth", "pip": 1, "conf": 0.95}]}, 0.9)   # confident read
    assert b.fails[3] == 0


def test_record_keys():
    r = sp.Burster.record("g", 5.04, [3], 5, [1, 2], {3: [{"type": "Growth", "pip": 1, "conf": 0.9}]},
                          {3: ("Growth", 1)}, {3: None}, {2}, False)
    assert list(r) == ["game", "t", "cells", "grabs", "kept", "reads", "result", "memory", "buffed", "glare"]
    assert r["reads"] == {"3": [["Growth", 1, 0.9]]} and r["result"] == {"3": ["Growth", 1]}
    assert r["memory"] == {"3": None} and r["kept"] == 2
    json.dumps(r)


def test_maybe_save_gap_cap_and_covered():
    p = Player(saver=Saver([None, ["a"]]))
    b = sp.Burster(p)
    assert b.maybe_save("g", 1.0, [3], [1], {}) is None          # covered
    assert b.saved == 0
    assert b.maybe_save("g", 1.0, [3], [1], {}) == ["a"]         # retried at once: gap not consumed
    p.clock.t += 9.9
    assert b.maybe_save("g", 2.0, [3], [1], {}) is None
    assert len(p.saver.calls) == 2
    for _ in range(80):
        p.clock.t += 10.0
        b.maybe_save("g", 3.0, [3], [1], {})
    assert b.saved == sp.BURST_SAVE_MAX


def test_saver_burst_reads_unobscured_at_call_time(monkeypatch):
    calls = []
    monkeypatch.setattr(collect, "save_burst",
                        lambda gid, t, cells, grabs, unobscured, record: calls.append(unobscured))
    g = G()
    s = sb.Saver(g)
    s.burst("g", 1.0, [3], [], {})
    g.clear = False
    s.burst("g", 2.0, [3], [], {})
    assert calls == [True, False]
