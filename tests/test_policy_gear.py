from rdom.policy.gear import evaluate, plan_next, can_merge, gear_components


def board(spec):
    """spec: 15 tokens like 'G2' (Gear pip2), 'B1', 'A1', 'R1' (Growth), 'D1', '.' (empty)."""
    T = {"G": "Gear", "B": "Bubble", "A": "Adjust", "R": "Growth", "D": "Doom"}
    out = []
    for i, tok in enumerate(spec.split(), 1):
        if tok == ".":
            out.append({"cell": i, "type": "empty", "pip": 0})
        else:
            out.append({"cell": i, "type": T[tok[0]], "pip": int(tok[1])})
    return out


FINAL = board("G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 G2 G2")


def test_final_field_complete_still_merges_after_transcend():
    ev = evaluate(FINAL)
    assert ev["complete"], ev
    assert plan_next(FINAL, transcended=False)["op"] == "wait"
    assert plan_next(FINAL, transcended=True)["op"] == "wait"   # complete -> maintain


def test_low_average_not_complete():
    b = board("G1 G1 G1 B1 G1  G1 B2 G1 G1 G1  G1 G1 G1 G1 G1")
    assert not evaluate(b)["complete"]


def test_disconnected_gears_not_complete():
    b = board("G2 B1 G2 G2 G2  B1 B1 G2 G2 G2  G2 G2 G2 G2 G2")   # cell 1 cut off
    assert len(gear_components(b)) == 2
    assert not evaluate(b)["complete"]


def test_empty_cell_summons():
    b = board(". G1 G1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 B1 B1")
    assert plan_next(b)["op"] == "summon"


def test_growth_never_merged():
    b = board("R1 R1 G1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 B1 B1")
    a = plan_next(b, transcended=False)
    assert a["op"] != "merge" or 1 not in (a["from"], a["to"]) and 2 not in (a["from"], a["to"])


def test_adjust_merges_any_same_pip():
    assert can_merge({"cell": 1, "type": "Adjust", "pip": 2}, {"cell": 2, "type": "Bubble", "pip": 2})
    assert not can_merge({"cell": 1, "type": "Adjust", "pip": 2}, {"cell": 2, "type": "Bubble", "pip": 1})


def test_phase_a_frees_cell_next_to_gears_and_keeps_gears():
    # Doom pair: cell 8 sits inside the gear block, cell 15 is the outer corner
    b = board("G1 G1 G1 G1 B1  G1 G1 D1 G1 B1  G1 G1 G1 A2 D1")
    a = plan_next(b, transcended=False)
    assert a == {"op": "merge", "from": 8, "to": 15}, a


def test_phase_a_does_not_merge_gears():
    b = board("G1 G1 G1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 B1 B1")
    assert plan_next(b, transcended=False)["op"] == "wait"


def test_three_bubbles_are_fodder():
    # safe zone 1-3, best 2: a 3rd bubble is not hoarded (user 2026-10-10)
    b = board("B1 B1 B1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 G1 G1")
    a = plan_next(b, transcended=False)
    assert a["op"] == "merge", a
    assert {b[a["from"] - 1]["type"], b[a["to"] - 1]["type"]} == {"Bubble"}


def test_bubble_pair_never_risks_zero():
    # 2 bubbles: merging both could leave 0 (result is random) -> not allowed
    b = board("B1 B1 G1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 G1 G1")
    assert plan_next(b, transcended=False)["op"] == "wait"


def test_phase_b_merges_low_gears_when_average_short():
    b = board("G1 G1 G2 B1 G2  G2 B2 G2 G2 G2  G2 G2 G2 G2 G2")
    a = plan_next(b, transcended=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {1, 2}, a


def test_banned_pair_skipped():
    b = board("G1 G1 G1 G1 B1  G1 G1 D1 G1 B1  G1 G1 G1 A2 D1")
    a = plan_next(b, transcended=False, banned={(8, 15)})
    assert a != {"op": "merge", "from": 8, "to": 15}


def test_support_used_when_stuck():
    b = board("G1 G1 G1 G1 B1  G1 G1 D2 G1 B1  G1 G1 G1 G1 R1")
    assert plan_next(b, transcended=False, support_ready=True) == {"op": "support", "from": 8}
    assert plan_next(b, transcended=False, support_ready=False)["op"] == "wait"


def test_walled_in_gear_rerolls_the_separating_bubble():
    # live 2026-10-07: gear in cell 5 cut off by bubbles in 4 and 10
    b = board("G2 G3 G1 B3 G3  G5 B1 G2 G2 B2  G1 G1 G1 G2 G2")
    assert not evaluate(b)["connected"]
    a = plan_next(b, transcended=True, support_ready=True)
    assert a["op"] == "support" and a["from"] in (4, 10), a


def test_phase_b_high_pip_gears_only_when_average_short():
    # avg >= 2: G2 pair must not merge, G1 pair may
    # two odd dice (no partners) keep it from complete / near-complete
    b = board("G1 G1 G3 B1 G3  G3 B2 G2 G2 G3  G3 G3 G3 R2 D3")
    a = plan_next(b, transcended=True)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {1, 2}, a
    b2 = board("G4 G3 G3 B1 G3  G3 B2 G2 G2 G3  G3 G3 G3 R2 D3")
    assert plan_next(b2, transcended=True)["op"] == "wait"


def test_near_complete_uses_supporter_and_does_not_merge():
    b = board("G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 G2 D1")   # one Doom left
    from rdom.policy.gear import near_complete
    assert near_complete(b)
    assert plan_next(b, transcended=True, support_ready=True) == {"op": "support", "from": 15}
    assert plan_next(b, transcended=True, support_ready=False)["op"] == "wait"


def test_clone_alert_rerolls_non_gear_maximum():
    # bubble 5 is the highest die -> it would be copied; reroll it
    b = board("G2 G3 G3 B5 G3  G3 B2 G2 G2 G3  G3 G3 G3 R2 D3")
    a = plan_next(b, transcended=True, support_ready=True, clone_alert=True)
    assert a == {"op": "support", "from": 4}, a


def test_clone_alert_blocks_merges_that_could_top_the_gears():
    # G3+G3 -> random pip 4 > every gear: not during the alert
    b = board("G3 G3 G1 B1 G1  G1 B2 G2 G2 G1  G1 G1 G1 R2 D2")
    a = plan_next(b, transcended=True, support_ready=False, clone_alert=True)
    assert not (a["op"] == "merge" and {a["from"], a["to"]} == {1, 2}), a


def _with_crystal(b, *cells):
    for c in cells:
        b[c - 1] = {"cell": c, "type": "Crystal", "pip": 0}
    return b


def test_crystal_blocks_completion_and_never_merges():
    from rdom.policy.gear import can_merge
    b = _with_crystal(board("G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 G2 G2"), 15)
    ev = evaluate(b)
    assert not ev["complete"] and ev["crystals"] == [15] and ev["unknown"] == 0
    assert not can_merge({"cell": 1, "type": "Crystal", "pip": 0}, {"cell": 2, "type": "Crystal", "pip": 0})


def test_crystal_prefers_merges_next_to_it():
    # crystal in cell 1; Doom pair 2 (next to it) and 9 -- and Adjust pair 13/15 far away
    b = _with_crystal(board("G1 D2 G1 G1 G1  G1 G1 G1 D2 G1  G1 G1 A1 G1 A1"), 1)
    a = plan_next(b, transcended=False)
    assert a["op"] == "merge" and a["to"] == 2, a


def test_crystal_after_transcend_uses_gear_pair_if_needed():
    b = _with_crystal(board("G1 G1 G3 B1 G3  G2 B2 G3 G2 G3  G3 G3 G3 G2 G2"), 1)
    a = plan_next(b, transcended=True)
    assert a["op"] == "merge" and a["to"] in (2, 6), a   # lands next to the crystal


def test_crystal_merge_must_land_next_to_it():
    # only partner of the Doom next to the crystal is far away: merge must land on 2
    b = _with_crystal(board("G1 D2 G1 G1 G1  G1 G1 G1 G1 G1  G1 G1 G1 G1 D2"), 1)
    a = plan_next(b, transcended=False)
    assert a == {"op": "merge", "from": 15, "to": 2}, a


def _with(b, cell, typ, pip):
    b[cell - 1] = {"cell": cell, "type": typ, "pip": pip}
    return b


def test_joker_copies_same_pip_gear_first():
    b = _with(board("G1 G2 G1 G1 B1  G1 G1 D2 G1 B1  G1 G1 G1 A2 D2"), 7, "Joker", 2)
    a = plan_next(b, transcended=False)
    assert a == {"op": "merge", "from": 7, "to": 2}, a       # joker -> the only Gear 2


def test_joker_never_used_as_normal_merge_partner():
    from rdom.policy.gear import can_merge
    assert not can_merge({"cell": 1, "type": "Joker", "pip": 2}, {"cell": 2, "type": "Adjust", "pip": 2})


def test_joker_without_matching_gear_waits():
    b = _with(board("G1 G1 G1 G1 B1  G1 G1 G1 G1 B1  G1 G1 G1 G1 G1"), 7, "Joker", 3)
    a = plan_next(b, transcended=True)
    assert not (a["op"] == "merge" and 7 in (a["from"], a["to"])), a   # no pip-3 target


def test_doom_pip_is_exact():
    from rdom.policy.gear import can_merge
    doom3 = {"cell": 1, "type": "Doom", "pip": 3}
    assert can_merge(doom3, {"cell": 2, "type": "Adjust", "pip": 3})
    assert not can_merge(doom3, {"cell": 2, "type": "Adjust", "pip": 2})


def test_bomb_order_pair_then_adjust1_then_supporter():
    b = _with(_with(board("G1 G1 G1 G1 B1  G1 G1 G1 G1 B1  G1 A1 A2 G1 G1"), 3, "Bomb", 0), 9, "Bomb", 0)
    a = plan_next(b, transcended=False)
    assert a["op"] == "merge" and {a["from"], a["to"]} == {3, 9}, a          # 1. bomb+bomb
    b = _with(board("G1 G1 G1 G1 B1  G1 G1 G1 G1 B1  G1 A2 A1 G1 G1"), 3, "Bomb", 0)
    a = plan_next(b, transcended=False)
    assert a == {"op": "merge", "from": 3, "to": 13}, a                       # 2. bomb+Adjust pip1
    b = _with(board("G1 G1 G1 G1 B1  G1 G1 G1 G1 B1  G1 A2 A2 G1 G1"), 3, "Bomb", 0)
    assert plan_next(b, transcended=False, support_ready=True) == {"op": "support", "from": 3}   # 3.
    assert not evaluate(b)["complete"]


# ---- deck rule from config/deck.toml [keep] (부패 deck, user 2026-10-11) ----
import os, tempfile
import rdom.policy.gear as pg


def _decay_deck():
    f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    f.write("[keep]\nBubble = [1, 2]\nDecay = [1, 2]\n"); f.close()
    old = pg.KEEP
    pg.load_deck(f.name); os.unlink(f.name)
    return old


def _with_decay(spec):
    b = board(spec.replace("X", "D"))
    for d in b:
        if d["type"] == "Doom":
            d["type"] = "Decay"
    return b


def test_decay_deck_complete():
    old = _decay_deck()
    try:
        ok = _with_decay("G2 G2 G3 B1 G2  G3 X2 G2 G2 G2  G2 G2 G3 G2 G2")      # 1 bubble, 1 decay
        assert evaluate(ok)["complete"]
        no_decay = board("G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 G2 G2")     # decay 0 -> not done
        assert not evaluate(no_decay)["complete"]
        three_bub = _with_decay("G2 G2 G3 B1 G2  G3 X2 B2 G2 G2  G2 B3 G3 G2 G2")  # 3 bubbles > 2
        assert not evaluate(three_bub)["complete"]
    finally:
        pg.KEEP = old


def test_decay_deck_keeps_one_decay():
    old = _decay_deck()
    try:
        b = _with_decay("X1 X1 G1 G1 G1  G1 B1 G1 G1 G1  G1 G1 G1 G1 B2")      # 2 decay, both pip 1
        a = plan_next(b, transcended=False)
        assert not (a["op"] == "merge" and {b[a["from"] - 1]["type"], b[a["to"] - 1]["type"]} == {"Decay"}), a
    finally:
        pg.KEEP = old


def test_surplus_decay_merged_not_waited():
    # 3 decay with 1-2 allowed, field otherwise done, after 초월: merge decay away
    # instead of "near-complete: supporter cooldown" (user 2026-10-11)
    old = _decay_deck()
    try:
        b = _with_decay("G2 G2 G3 B1 G2  G3 X1 G2 X1 G2  G2 X2 G3 G2 G2")
        a = plan_next(b, transcended=True, support_ready=False)
        assert a["op"] == "merge", a
        assert {b[a["from"] - 1]["type"], b[a["to"] - 1]["type"]} == {"Decay"}, a
    finally:
        pg.KEEP = old


def test_doom_deck_bubbles_one_to_three_complete():
    b = board("G2 G2 G3 B1 G2  G3 B2 G2 G2 G2  G2 G2 G3 B2 G2")    # 3 bubbles: still complete
    assert evaluate(b)["complete"]
