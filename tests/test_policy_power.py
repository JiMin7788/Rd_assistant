import ast
from pathlib import Path

from rdom.policy.power import (CARDS, INITIAL, PowerConfig, PowerTracker,
                               load_power_config, next_card, plan_visit)

ROOT = Path(__file__).resolve().parents[1]
ALL = CARDS
G, A, R = "Growth", "Alignment", "Resonance"


def lv(g, a, r):
    return {G: g, A: a, R: r}


def test_defaults_and_real_file():
    d = PowerConfig()
    assert (d.growth_first, d.ratio, d.growth_late, d.growth_late_after) == (7, (3, 1), 8, 8)
    assert load_power_config(ROOT / "config" / "deck.toml") == d
    assert INITIAL == 1


def test_load_missing(tmp_path):
    assert load_power_config(tmp_path / "none.toml") == PowerConfig()
    p = tmp_path / "d.toml"
    p.write_text("[decks.support]\ndice = []\n", encoding="utf-8")
    assert load_power_config(p) == PowerConfig()
    p.write_text("[decks.support]\npower_growth_first = 5\npower_ratio = [2, 1]\n", encoding="utf-8")
    c = load_power_config(p)
    assert c.growth_first == 5 and c.ratio == (2, 1) and c.growth_late == 8


def test_next_card_all():
    cases = [((1, 1, 1), G), ((7, 1, 1), A), ((7, 4, 1), R), ((7, 4, 2), A),
             ((7, 7, 3), G), ((8, 7, 3), A)]
    for levels, want in cases:
        assert next_card(lv(*levels), ALL) == want, levels


def test_next_card_limited():
    assert next_card(lv(1, 1, 1), (A, R)) == A
    assert next_card(lv(8, 1, 1), (R, G)) == R
    assert next_card(lv(7, 1, 1), (G,)) == G
    assert next_card(lv(8, 1, 1), (G,)) is None


def test_plan_visit():
    assert plan_visit(lv(1, 1, 1), ALL) == [G] * 6
    assert plan_visit(lv(7, 1, 1), ALL) == [A, A, A, R, A, A]
    assert plan_visit(lv(7, 7, 2), ALL) == [R, G, A, A, A, R]
    assert plan_visit(lv(7, 1, 1), ALL, PowerConfig(ratio=(2, 1))) == [A, A, R, A, A, R]
    assert plan_visit(lv(7, 1, 1), (), n=6) == []


def test_tracker_levels():
    t = PowerTracker()
    levels, src, lines = t.start_visit(lv(3, 1, 1))
    assert levels == lv(3, 1, 1) and src == "read" and lines == []
    t.tapped([G] * 3)
    levels, src, _ = t.start_visit({G: None, A: 1, R: 1})
    assert levels[G] == 6 and src == "count"
    t.tapped([G])
    levels, src, _ = t.start_visit(lv(5, 1, 1))
    assert levels[G] == 5 and src == "read"
    levels, _, _ = t.start_visit({G: None, A: 1, R: 1})
    assert levels[G] == 5          # taps were cleared by the read
    t2 = PowerTracker()
    t2.tapped([A, A])
    levels, src, _ = t2.start_visit({G: None, A: None, R: None})
    assert levels == lv(1, 3, 1) and src == "count"


def _maxed_setup():
    t = PowerTracker()
    t.start_visit(lv(1, 4, 1))
    return t


def test_maxed_after_two_strikes():
    t = _maxed_setup()
    t.tapped([A, G])
    _, _, lines = t.start_visit(lv(2, 4, 1))      # Growth rose, Alignment did not: strike 1
    assert lines == [] and A in t.available()
    t.tapped([A, G])
    _, _, lines = t.start_visit(lv(3, 4, 1))      # strike 2
    assert lines == ["power card Alignment maxed at Lv 4"]
    assert A not in t.available()
    t.tapped([G])
    _, _, lines = t.start_visit(lv(4, 4, 1))
    assert lines == []
    assert t.record()["maxed"] == [A]


def test_no_strike_without_rise_or_unread_or_after_rise():
    t = _maxed_setup()
    for _ in range(3):
        t.tapped([A, G])
        t.start_visit(lv(1, 4, 1))                # nothing rose: no SP
    assert A in t.available()
    t.tapped([A, G])
    t.start_visit(lv(2, 4, 1))                    # strike 1
    t.tapped([A, G])
    t.start_visit({G: None, A: None, R: 1})       # unread: no strike
    assert A in t.available()
    t.start_visit(lv(2, 4, 1))                    # baseline read again
    t.tapped([A, G])
    t.start_visit(lv(4, 5, 1))                    # both rose: strikes reset
    t.tapped([A, G])
    _, _, lines = t.start_visit(lv(5, 5, 1))      # strike 1 only
    assert lines == [] and A in t.available()


def test_line_and_record():
    seq = [A, A, A, R, A, A]
    assert PowerTracker.line(seq, lv(7, 1, 1), "read") == \
        "power panel -> AAARAA, close (Lv G7 A1 R1, read)"
    assert PowerTracker.line([A, A, A, R], lv(None, 2, 1), "count") == \
        "power panel -> AAAR, close (Lv G- A2 R1, count)"
    t = PowerTracker()
    assert t.record() is None
    t.start_visit(lv(2, 1, 1))
    assert t.record() == {"levels": lv(2, 1, 1), "src": "read", "maxed": []}


def test_imports_stdlib_only():
    tree = ast.parse((ROOT / "src" / "rdom" / "policy" / "power.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"__future__", "dataclasses", "tomllib", "math"}
