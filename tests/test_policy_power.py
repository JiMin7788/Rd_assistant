import ast
from pathlib import Path

from rdom.policy.power import (CARDS, INITIAL, PowerConfig, PowerTracker, keep,
                               load_power_config, next_card, plan_visit)

ROOT = Path(__file__).resolve().parents[1]
ALL = CARDS
G, A, R = "Growth", "Alignment", "Resonance"


def lv(g, a, r):
    return {G: g, A: a, R: r}


def test_defaults_and_real_file():
    d = PowerConfig()
    assert (d.growth_first, d.ratio, d.growth_late, d.growth_late_after) == (7, (3, 1), 8, 8)
    assert d.reserve_x == 3
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


def test_levels_are_confirmed_purchase_count():
    t = PowerTracker()
    assert t.levels() == lv(1, 1, 1)
    t.confirmed(G, 100)
    t.confirmed(G, 120)
    t.confirmed(A, 90)
    assert t.levels() == lv(3, 2, 1)
    assert t.last_price(G) == 120 and t.last_price(R) is None


def test_lv_check_equal():
    t = PowerTracker()
    t.confirmed(G, 1)
    assert t.start_visit(lv(2, 1, 1)) == ["Lv check: read G2 A1 R1 = count"]
    assert t.start_visit({G: 2, A: None, R: 1}) == ["Lv check: read G2 A- R1 = count"]


def test_lv_check_mismatch_keeps_count():
    t = PowerTracker()
    t.confirmed(G, 1)
    lines = t.start_visit(lv(5, 1, 3))
    assert lines == ["Lv check: Growth read 5, count 2 (count kept)",
                     "Lv check: Resonance read 3, count 1 (count kept)"]
    assert t.levels() == lv(2, 1, 1)


def test_lv_check_field_effect_leaves_levels():
    t = PowerTracker()
    t.confirmed(G, 1)
    lines = t.start_visit(lv(3, 2, 2))
    assert lines == ["Lv check: read G3 A2 R2 = count +1 on every card (field effect)"]
    assert t.levels() == lv(2, 1, 1)
    # two read cards both +1 is enough; one read card +1 is only a mismatch
    assert t.start_visit({G: 3, A: 2, R: None}) == \
        ["Lv check: read G3 A2 R- = count +1 on every card (field effect)"]
    assert t.start_visit({G: 3, A: None, R: None}) == ["Lv check: Growth read 3, count 2 (count kept)"]
    # +1 on one card and equal on another is not the field effect
    assert t.start_visit(lv(3, 1, 1)) == ["Lv check: Growth read 3, count 2 (count kept)"]


def test_lv_check_not_read_and_not_found():
    t = PowerTracker()
    assert t.start_visit({G: None, A: None, R: None}) == ["Lv check: not read"]
    # a card not found on the panel counts as not read
    assert t.start_visit(lv(1, 1, 1), found={G, R}) == ["Lv check: read G1 A- R1 = count"]
    assert t.levels() == lv(1, 1, 1)


def test_maxed_after_two_qualifying_strikes():
    t = PowerTracker()
    t.confirmed(A, 1)
    t.start_visit(lv(2, 1, 1))
    assert t.not_confirmed(A, True, True) == []
    assert A in t.available()
    assert t.not_confirmed(A, True, True) == ["power card Alignment maxed at Lv 2"]
    assert A not in t.available()
    assert t.record()["maxed"] == [A]


def test_no_strike_when_not_affordable_or_sp_unknown():
    t = PowerTracker()
    for _ in range(4):
        assert t.not_confirmed(G, False, True) == []
        assert t.not_confirmed(G, True, False) == []
    assert G in t.available()
    assert t.not_confirmed(G, True, True) == []
    assert t.not_confirmed(G, False, True) == []      # no information: strike kept, none added
    assert t.not_confirmed(G, True, True) == ["power card Growth maxed at Lv 1"]


def test_confirmed_resets_strikes():
    t = PowerTracker()
    t.not_confirmed(R, True, True)
    t.confirmed(R, 50)
    assert t.not_confirmed(R, True, True) == []
    assert R in t.available()
    assert t.not_confirmed(R, True, True) == ["power card Resonance maxed at Lv 2"]


def test_keep_and_reserve_config(tmp_path):
    assert PowerConfig().reserve_x == 3
    assert keep(480) == 1440 and keep(100, PowerConfig(reserve_x=2)) == 200
    p = tmp_path / "d.toml"
    p.write_text("[decks.support]\ndice = []\n", encoding="utf-8")
    assert load_power_config(p).reserve_x == 3
    p.write_text("[decks.support]\npower_reserve_x = 5\n", encoding="utf-8")
    assert load_power_config(p).reserve_x == 5
    text = (ROOT / "config" / "deck.toml").read_text(encoding="utf-8")
    assert "power_reserve_x = 3" in text
    assert text.index("[decks.decay]") < text.index("[decks.support]") < text.index("power_reserve_x")


def test_line():
    assert PowerTracker.line("GGa", lv(3, 1, 1), 9800, 1440, 2) == \
        "power panel -> GGa (2 bought), close (Lv G3 A1 R1, SP 9800, keep 1440)"


def test_record_shape():
    t = PowerTracker()
    assert t.record() is None
    t.start_visit(lv(1, 1, 1))
    assert t.record() == {"levels": lv(1, 1, 1), "src": "count", "maxed": [], "bought": 0,
                          "unconfirmed": 0, "visits": 1,
                          "lv_check": {"ok": 1, "field": 0, "mismatch": 0, "unread": 0},
                          "price": {G: None, A: None, R: None}}
    t.confirmed(A, 70)
    t.not_confirmed(G, False, True)
    t.start_visit(lv(3, 3, 3))          # count A2 G1 R1: A+2, G+2, R+2 -> mismatch
    t.start_visit(lv(2, 3, 2))          # every card count+1 -> field effect
    t.start_visit({G: None, A: None, R: None})
    r = t.record()
    assert set(r) == {"levels", "src", "maxed", "bought", "unconfirmed", "visits", "lv_check", "price"}
    assert r["levels"] == lv(1, 2, 1) and r["bought"] == 1 and r["unconfirmed"] == 1
    assert r["visits"] == 4 and r["price"][A] == 70
    assert r["lv_check"] == {"ok": 1, "field": 1, "mismatch": 1, "unread": 1}


def test_imports_stdlib_only():
    tree = ast.parse((ROOT / "src" / "rdom" / "policy" / "power.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"__future__", "dataclasses", "tomllib", "math"}
