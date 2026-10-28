import ast
from pathlib import Path

from rdom.policy import milestones
from rdom.policy.milestones import CROSSINGS, MILESTONES, MilestoneTracker


def c(r, a, b):
    return {"res7": r, "align7": a, "bubbles": b}


def test_constants():
    assert MILESTONES == (("m1", 2000, 1, 1, 0), ("m2", 3000, 2, 1, 0), ("m3", 4000, 2, 3, 2))
    assert CROSSINGS == (2000, 3000, 4000)


def test_reached_once():
    t = MilestoneTracker()
    t.on_score(1500)
    ev = t.on_board(c(1, 1, 3))
    assert len(ev) == 1
    assert ev[0]["name"] == "m1" and ev[0]["score"] == 1500 and ev[0]["late"] is False
    assert ev[0]["log"] == "milestone m1 reached at score 1500 (Res7 1, Align7 1, Bubble 3)"
    assert t.on_board(c(1, 1, 3)) == []


def test_late_is_not_reached():
    t = MilestoneTracker()
    t.on_score(3150)
    ev = t.on_board(c(2, 1, 2))
    names = {e["name"]: e for e in ev}
    assert names["m2"]["late"] is True
    assert names["m2"]["log"] == "milestone m2 late at score 3150 (Res7 2, Align7 1, Bubble 2)"
    rec = t.record()["milestones"]["m2"]
    assert rec["reached"] is False and rec["late"] is True and rec["score"] == 3150


def test_unknown_score_counts_as_reached():
    t = MilestoneTracker()
    ev = t.on_board(c(1, 1, 0))
    assert ev[0]["score"] is None and ev[0]["late"] is False
    assert ev[0]["log"] == "milestone m1 reached at score ? (Res7 1, Align7 1, Bubble 0)"
    rec = t.record()["milestones"]["m1"]
    assert rec["reached"] is True and rec["score"] is None


def test_crossings():
    t = MilestoneTracker()
    t.on_board(c(1, 2, 3))
    assert t.on_score(1990) == []
    ev = t.on_score(2010)
    assert len(ev) == 1 and ev[0]["limit"] == 2000
    assert ev[0]["log"] == "score crossed 2000 (Res7 1, Align7 2, Bubble 3)"
    t.on_board(c(2, 3, 2))
    ev = t.on_score(4100)
    assert [e["limit"] for e in ev] == [3000, 4000]
    assert ev[0]["log"] == "score crossed 3000 (Res7 2, Align7 3, Bubble 2)"
    assert t.on_score(4200) == []


def test_record_and_set_shot():
    t = MilestoneTracker()
    t.on_board(c(1, 1, 0))
    t.on_score(1000)
    ev = t.on_board(c(1, 1, 1))
    assert ev == []
    t.on_score(2500)
    ms_ev = MilestoneTracker()
    ms_ev.on_score(500)
    m = ms_ev.on_board(c(1, 1, 1))[0]
    ms_ev.set_shot(m, "a/m1.png")
    cr = ms_ev.on_score(2100)[0]
    ms_ev.set_shot(cr, "a/c2000.png")
    rec = ms_ev.record()
    assert set(rec["milestones"]) == {"m1", "m2", "m3"}
    assert rec["milestones"]["m1"] == {"reached": True, "late": False, "score": 500,
                                       "shot": "a/m1.png"}
    assert rec["milestones"]["m2"] == {"reached": False, "late": False, "score": None,
                                       "shot": None}
    assert set(rec["crossings"]) == {"2000", "3000", "4000"}
    assert rec["crossings"]["2000"] == {"res7": 1, "align7": 1, "bubbles": 1, "score": 2100,
                                        "shot": "a/c2000.png"}
    assert rec["max_score"] == 2100 and rec["scores_confirmed"] == 2
    assert t.record()["max_score"] == 2500


def test_no_io_or_perception_imports():
    tree = ast.parse(Path(milestones.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert not any(m.startswith(("rdom.perception", "cv2", "torch")) for m in mods)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)}
    assert "open" not in calls and "print" not in calls
