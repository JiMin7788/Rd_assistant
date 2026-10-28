import ast
from pathlib import Path

from rdom.policy import support
from rdom.policy.support import (DEFAULT, can_merge_support, evaluate_support,
                                 load_support_deck, plan_support)

ROOT = Path(__file__).resolve().parents[1]
T = {"R": "Resonance", "L": "Alignment", "B": "Bubble", "A": "Adjust", "G": "Growth",
     "J": "Joker", "X": "Bomb", "C": "Crystal"}


def tok(cell, t):
    if t == ".":
        return {"cell": cell, "type": "empty", "pip": 0}
    if t == "?":
        return {"cell": cell, "type": "junk", "pip": 0}
    if t == "X" or t == "C":
        return {"cell": cell, "type": T[t], "pip": 0}
    return {"cell": cell, "type": T[t[0]], "pip": int(t[1])}


def board(spec):
    """spec: 15 tokens such as 'R6', 'L7', 'B2', 'A3', 'G1', 'J2', 'X', 'C', '.', '?'."""
    return [tok(i, t) for i, t in enumerate(spec.split(), 1)]


def sparse(cells):
    """{cell: token}; every other cell is an inert Growth 7 (never merged, never rerolled)."""
    return [tok(i, cells.get(i, "G7")) for i in range(1, 16)]


def d(cell, t, pip):
    return {"cell": cell, "type": t, "pip": pip}


COMPLETE = {1: "R7", 2: "R7", 3: "L7", 4: "L7", 5: "L7", 6: "B2", 7: "B3"}


# --- config (AC1, AC2) ---------------------------------------------------------
def test_load_real_file_and_fallbacks(tmp_path):
    deck = load_support_deck(ROOT / "config" / "deck.toml")
    assert deck.dice == ("Resonance", "Alignment", "Bubble", "Adjust", "Growth")
    assert deck.keep == {"Bubble": (2, 3, 3)}
    assert (deck.res7, deck.align7_min, deck.align_cols) == (2, 3, (2, 3, 4))
    assert deck == DEFAULT
    assert load_support_deck(tmp_path / "missing.toml") == DEFAULT
    other = tmp_path / "other.toml"
    other.write_text('active = "doom"\n[decks.doom]\nkeep = { Bubble = [1, 3, 1] }\n')
    assert load_support_deck(other) == DEFAULT


def test_load_overrides_values(tmp_path):
    p = tmp_path / "d.toml"
    p.write_text('[decks.support]\nres7 = 3\nalign_cols = [1]\nkeep = { Bubble = [1, 2] }\n')
    deck = load_support_deck(p)
    assert deck.res7 == 3 and deck.align_cols == (1,) and deck.keep == {"Bubble": (1, 2, 2)}
    assert deck.align7_min == 3


def test_deck_toml_order_keeps_doom_first():
    import tomllib
    cfg = tomllib.loads((ROOT / "config" / "deck.toml").read_text(encoding="utf-8"))
    assert cfg["active"] == "doom" and cfg["force"] == ""
    assert list(cfg["decks"]) == ["doom", "decay", "support"]


# --- evaluate (AC3) -------------------------------------------------------------
def test_evaluate_counts_and_complete():
    ev = evaluate_support(sparse(COMPLETE))
    assert (ev["res7"], ev["align7"], ev["bubbles"]) == (2, 3, 2)
    assert ev["empty"] == 0 and ev["unknown"] == 0 and ev["bombs"] == [] and ev["crystals"] == []
    assert ev["complete"] is True
    for drop in (1, 3, 6):                       # one Res7 / one Align7 / one Bubble short
        short = {c: t for c, t in COMPLETE.items() if c != drop}
        assert evaluate_support(sparse(short))["complete"] is False


def test_evaluate_complete_ignores_other_cells():
    b = sparse({**COMPLETE, 8: "B1", 9: "B1", 10: "?", 11: "X", 12: "C", 13: "."})
    ev = evaluate_support(b)
    assert ev["complete"] is True and ev["bubbles"] == 4
    assert (ev["empty"], ev["unknown"], ev["bombs"], ev["crystals"]) == (1, 1, [11], [12])


# --- can_merge_support (AC4) ----------------------------------------------------
def test_can_merge_rules():
    for pip in range(1, 7):
        assert can_merge_support(d(1, "Resonance", pip), d(2, "Resonance", pip))
        assert can_merge_support(d(1, "Adjust", pip), d(2, "Bubble", pip))
        assert can_merge_support(d(1, "Alignment", pip), d(2, "Adjust", pip))
    assert not can_merge_support(d(1, "Resonance", 2), d(2, "Resonance", 3))
    assert not can_merge_support(d(1, "Adjust", 2), d(2, "Bubble", 3))
    assert not can_merge_support(d(1, "Resonance", 3), d(2, "Alignment", 3))
    assert not can_merge_support(d(1, "Resonance", 7), d(2, "Resonance", 7))
    assert not can_merge_support(d(1, "Adjust", 7), d(2, "Resonance", 7))
    assert not can_merge_support(d(1, "Resonance", 2), d(1, "Resonance", 2))      # same cell
    for t in ("Growth", "Joker", "Crystal", "empty", "junk"):
        assert not can_merge_support(d(1, t, 2), d(2, t, 2))
        assert not can_merge_support(d(1, t, 2), d(2, "Adjust", 2))
        assert not can_merge_support(d(1, "Resonance", 2), d(2, t, 2))


def test_can_merge_bomb():
    assert can_merge_support(d(1, "Bomb", 0), d(2, "Bomb", 0))
    assert can_merge_support(d(1, "Bomb", 0), d(2, "Adjust", 1))
    assert can_merge_support(d(1, "Adjust", 1), d(2, "Bomb", 0))
    assert not can_merge_support(d(1, "Bomb", 0), d(2, "Adjust", 2))
    assert not can_merge_support(d(1, "Bomb", 0), d(2, "Resonance", 1))


# --- summon / keep minimum / pip 7 / growth (AC5-AC7) -------------------------------
def test_empty_cell_summons():
    assert plan_support(sparse({1: ".", 2: "R2", 3: "R2"})) == {"op": "summon"}
    assert plan_support(sparse({1: ".", 2: "X", 3: "X"}), support_ready=True) == {"op": "summon"}


def test_two_bubbles_never_consumed():
    b = sparse({1: "B3", 2: "B3"})
    assert plan_support(b)["op"] == "wait"
    # Bubble+Adjust would leave one Bubble
    b = sparse({1: "B3", 2: "B1", 3: "A3"})
    assert plan_support(b)["op"] == "wait"
    # another legal pair is fine, the Bubbles stay out of it
    b = sparse({1: "B3", 2: "B3", 6: "R2", 7: "R2"})
    a = plan_support(b)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {6, 7}


def test_three_bubbles_allow_one_bubble_merge():
    assert plan_support(sparse({1: "B3", 2: "B3", 3: "B3"}))["op"] == "wait"   # B+B leaves 1
    a = plan_support(sparse({1: "B3", 2: "B3", 3: "B3", 8: "A3"}))
    assert a["op"] == "merge" and 8 in (a["from"], a["to"])
    other = a["from"] if a["to"] == 8 else a["to"]
    assert other in (1, 2, 3)


def test_pip7_and_growth_pairs_not_merged():
    b = sparse({**COMPLETE, 8: "G4", 9: "G4", 10: "R7", 11: "A7"})
    assert plan_support(b)["op"] == "wait"
    assert all(t["type"] != "empty" for t in b)


# --- merge choice (AC8, AC9) ----------------------------------------------------
def test_highest_pip_first():
    a = plan_support(sparse({6: "R2", 7: "R2", 11: "L5", 12: "L5", 13: "R4", 14: "R4"}))
    assert a["op"] == "merge" and {a["from"], a["to"]} == {11, 12}


def test_adjust_prefers_res_align_over_bubble():
    b = sparse({6: "A3", 7: "B3", 11: "R3", 14: "B1", 15: "B2"})
    a = plan_support(b)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {6, 11}
    b = sparse({6: "A3", 7: "B3", 11: "L3", 14: "B1", 15: "B2"})
    a = plan_support(b)
    assert {a["from"], a["to"]} == {6, 11}
    # with only the Bubble partner the Adjust still merges
    a = plan_support(sparse({6: "A3", 7: "B3", 14: "B1", 15: "B2"}))
    assert {a["from"], a["to"]} == {6, 7}


def test_merge_lands_in_align_columns():
    assert plan_support(sparse({1: "R2", 2: "R2"})) == {"op": "merge", "from": 1, "to": 2}
    assert plan_support(sparse({2: "R2", 3: "R2"})) == {"op": "merge", "from": 3, "to": 2}
    assert plan_support(sparse({3: "R2", 4: "R2"})) == {"op": "merge", "from": 4, "to": 3}
    assert plan_support(sparse({5: "R2", 4: "R2"})) == {"op": "merge", "from": 5, "to": 4}


def test_surplus_bubble_is_consumed_first():
    b = sparse({1: "B4", 2: "B3", 3: "B2", 4: "B1", 6: "A2", 11: "R5", 12: "R5"})
    a = plan_support(b)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {3, 6}
    # three Bubbles are not surplus: the higher pip pair wins
    b = sparse({1: "B4", 2: "B3", 3: "B2", 6: "A2", 11: "R5", 12: "R5"})
    a = plan_support(b)
    assert {a["from"], a["to"]} == {11, 12}


# --- bombs (AC10) -----------------------------------------------------------------
def test_bomb_order():
    a = plan_support(sparse({1: "X", 2: "X", 3: "A1", 4: "X", 6: "R3", 7: "R3"}), support_ready=True)
    assert a["op"] == "merge" and a["from"] in (1, 2, 4) and a["to"] in (1, 2, 4)
    a = plan_support(sparse({1: "X", 3: "A1", 6: "R3", 7: "R3"}), support_ready=True)
    assert a == {"op": "merge", "from": 1, "to": 3}
    b = sparse({1: "X", 3: "A2", 6: "R3", 7: "R3"})
    assert plan_support(b, support_ready=True) == {"op": "support", "from": 1}
    assert plan_support(b, support_ready=False)["op"] != "support"


def test_bomb_without_supporter_waits():
    assert plan_support(sparse({4: "X", 3: "A2"})) == {"op": "wait", "why": "no move"}


# --- joker (AC11) -----------------------------------------------------------------
def test_joker_copies_alignment_over_resonance():
    a = plan_support(sparse({1: "J3", 2: "L3", 3: "R3"}))
    assert a == {"op": "merge", "from": 1, "to": 2}
    a = plan_support(sparse({1: "J3", 3: "R3"}))
    assert a == {"op": "merge", "from": 1, "to": 3}


def test_joker_bubble_only_while_short():
    assert plan_support(sparse({1: "J3", 2: "B3"})) == {"op": "merge", "from": 1, "to": 2}
    a = plan_support(sparse({1: "J3", 2: "B3", 3: "B1"}))
    assert a["op"] == "wait"
    assert plan_support(sparse({1: "J3", 2: "R4"}))["op"] == "wait"       # pips differ


# --- crystals (AC12) --------------------------------------------------------------
def test_crystal_chip_merge_preferred():
    # without the crystal the pip-5 pair on 4,5 would win
    cells = {4: "R5", 5: "R5", 11: "L2", 12: "L2", 13: "G2", 14: "G2"}
    a = plan_support(sparse(cells))
    assert {a["from"], a["to"]} == {4, 5}
    a = plan_support(sparse({**cells, 7: "C"}))
    assert a == {"op": "merge", "from": 11, "to": 12}     # 12 neighbours the crystal on 7
    assert not {a["from"], a["to"]} & {13, 14}


def test_crystal_with_only_growth_pair_does_not_merge_it():
    a = plan_support(sparse({7: "C", 11: "G2", 12: "G2", 6: "G1", 8: "G1"}))
    assert a["op"] == "wait"


# --- supporter (AC13) -------------------------------------------------------------
def test_supporter_adjust7_before_third_res7():
    b = sparse({1: "R7", 2: "R7", 3: "R7", 8: "A7"})
    assert plan_support(b, support_ready=True) == {"op": "support", "from": 8}
    assert plan_support(b, support_ready=False)["op"] == "wait"


def test_supporter_surplus_bubble_before_res7_and_lonely_adjust():
    b = sparse({1: "B2", 2: "B4", 3: "B5", 4: "B6", 5: "A3", 6: "R7", 7: "R7", 8: "R7"})
    assert plan_support(b, support_ready=True) == {"op": "support", "from": 4}


def test_supporter_third_res7():
    b = sparse({1: "R7", 2: "R7", 3: "R7"})
    assert plan_support(b, support_ready=True) == {"op": "support", "from": 1}
    assert plan_support(sparse({1: "R7", 2: "R7"}), support_ready=True)["op"] == "wait"


def test_supporter_lonely_adjust():
    assert plan_support(sparse({1: "A4"}), support_ready=True) == {"op": "support", "from": 1}
    assert plan_support(sparse({1: "A1"}), support_ready=True)["op"] == "wait"


def test_supporter_never_growth_alignment_or_pip1():
    b = sparse({1: "L5", 2: "L6", 3: "B1", 4: "A1", 5: "G4", 6: "L7", 7: "L7", 8: "L7", 9: "L7"})
    assert plan_support(b, support_ready=True)["op"] == "wait"
    b = sparse({1: "B1", 2: "B2", 3: "B3", 4: "B4"})
    assert plan_support(b, support_ready=True) == {"op": "support", "from": 4}


# --- clone alert (AC14) -------------------------------------------------------------
def test_clone_alert_rerolls_bubble_above_top():
    b = sparse({1: "L4", 2: "B5", 3: "R3"})
    assert plan_support(b, clone_alert=True, support_ready=True) == {"op": "support", "from": 2}
    assert plan_support(b, clone_alert=False, support_ready=True)["op"] != "support"
    assert plan_support(b, clone_alert=True, support_ready=False)["op"] == "wait"


def test_clone_alert_holds_back_new_maximum():
    b = sparse({1: "R4", 2: "R4"})
    assert plan_support(b, clone_alert=True)["op"] == "wait"
    assert plan_support(b, clone_alert=False) == {"op": "merge", "from": 1, "to": 2}
    # a merge that stays within the top is still fine
    a = plan_support(sparse({1: "R4", 6: "R2", 7: "R2"}), clone_alert=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {6, 7}


# --- wait reasons (AC15) --------------------------------------------------------------
def test_wait_reasons_and_merge_after_completion():
    assert plan_support(sparse(COMPLETE)) == {"op": "wait", "why": "complete"}
    assert plan_support(sparse({1: "R7"})) == {"op": "wait", "why": "no move"}
    a = plan_support(sparse({**COMPLETE, 8: "R2", 9: "R2"}))
    assert a["op"] == "merge" and {a["from"], a["to"]} == {8, 9}


# --- purity (AC16) ----------------------------------------------------------------------
def test_imports_are_pure():
    tree = ast.parse(Path(support.__file__).read_text(encoding="utf-8"))
    bad = ("rdom.perception", "tools", "cv2", "numpy", "torch")
    for n in ast.walk(tree):
        mods = [n.module or ""] if isinstance(n, ast.ImportFrom) else (
            [a.name for a in n.names] if isinstance(n, ast.Import) else [])
        for m in mods:
            assert not any(m == p or m.startswith(p + ".") for p in bad), m
            if m == "rdom.policy.gear" and isinstance(n, ast.ImportFrom):
                assert not any(a.name.startswith("_") for a in n.names)
