import ast
from pathlib import Path

from rdom.perception import support_memory as sm
from rdom.perception.support_memory import CellMemory, burst_result, merge_verdict

CM = 0.9


def rd(cell, typ="Resonance", pip=3, conf=0.99):
    return {"cell": cell, "type": typ, "variant": typ, "pip": pip, "conf": conf}


def junk(cell):
    return rd(cell, "junk", 0, 0.3)


def board(**over):
    """15 empty confident reads; over = {cell: read}."""
    b = [rd(c, "empty", 0, 0.99) for c in range(1, 16)]
    for c, d in over.items():
        b[int(c[1:]) - 1] = d
    return b


def cell(eff, c):
    return eff[c - 1]


def test_imports_pure():
    tree = ast.parse(Path(sm.__file__).read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add(n.module or "")
    assert not any(x.startswith(("cv2", "torch", "rdom.perception.gear", "numpy")) for x in names)
    assert "open(" not in Path(sm.__file__).read_text(encoding="utf-8")


def test_hacked_die_keeps_value_ten_ticks_one_event():
    m = CellMemory(CM)
    evs = []
    for _ in range(2):
        eff, e = m.update(board(c1=rd(1)))
        evs += e
    assert m.memory(1) == ("Resonance", 3) and m.state(1) == "readable"
    for _ in range(10):
        eff, e = m.update(board(c1=junk(1)))
        evs += e
        d = cell(eff, 1)
        assert (d["type"], d["pip"], d["src"]) == ("Resonance", 3, "memory")
        assert d["conf"] == 0.3
    assert [x for x in evs if x["kind"] == "remembered"] == [{"kind": "remembered", "cell": 1, "tok": "Re3"}]
    assert len(evs) == 1 and m.state(1) == "remembered"


def test_readable_cell_is_raw_read_and_single_read_sets_no_memory():
    m = CellMemory(CM)
    eff, _ = m.update(board(c1=rd(1)))
    assert cell(eff, 1)["src"] == "read" and m.memory(1) is None


def test_unknown_without_memory_never_empty():
    m = CellMemory(CM)
    low_empty = rd(2, "empty", 0, 0.5)
    eff, ev = m.update(board(c1=junk(1), c2=low_empty))
    for c in (1, 2):
        d = cell(eff, c)
        assert (d["type"], d["pip"], d["src"]) == ("junk", 0, "unknown")
    assert ev == [] and m.state(1) == "unknown"


def test_low_conf_empty_with_memory_keeps_memory():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1)))
    for _ in range(3):
        eff, _ = m.update(board(c1=rd(1, "empty", 0, 0.5)))
    assert cell(eff, 1)["type"] == "Resonance" and m.memory(1) == ("Resonance", 3)


def test_single_noisy_read_does_not_replace_two_identical_do():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2)))
    m.update(board(c1=rd(1, "Bubble", 1)))
    assert m.memory(1) == ("Alignment", 2)
    m.update(board(c1=rd(1, "Alignment", 2)))  # back to the memory resets pending
    m.update(board(c1=rd(1, "Bubble", 1)))
    assert m.memory(1) == ("Alignment", 2)
    m.update(board(c1=rd(1, "Bubble", 1)))
    assert m.memory(1) == ("Bubble", 1)


def test_pending_needs_identical_reads():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2)))
    m.update(board(c1=rd(1, "Bubble", 1)))
    m.update(board(c1=rd(1, "Adjust", 1)))
    assert m.memory(1) == ("Alignment", 2)


def test_unreadable_tick_keeps_pending():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2)))
    m.update(board(c1=rd(1, "Bubble", 1)))
    m.update(board(c1=junk(1)))
    m.update(board(c1=rd(1, "Bubble", 1)))
    assert m.memory(1) == ("Bubble", 1)


def test_empty_twice_drops_memory_and_is_external():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Bubble", 2)))
    _, e1 = m.update(board())
    assert m.memory(1) == ("Bubble", 2) and e1 == []
    eff, e2 = m.update(board())
    assert m.memory(1) is None and cell(eff, 1)["type"] == "empty"
    assert e2 == [{"kind": "external", "cells": [1], "forgot": []}]


def test_external_change_forgets_only_unreadable_cells():
    m = CellMemory(CM)
    full = lambda a, c5, c9: board(c1=a, c5=c5, c9=c9, c12=rd(12, "Resonance", 2))
    for _ in range(2):
        m.update(full(rd(1, "Alignment", 2), rd(5, "Bubble", 1), rd(9, "Adjust", 4)))
    assert m.state(5) == "readable"
    m.update(full(rd(1, "Alignment", 2), junk(5), junk(9)))
    assert m.state(5) == "remembered"
    all_ev = []
    for _ in range(2):
        eff, e = m.update(full(rd(1, "Bubble", 1), junk(5), junk(9)))
        all_ev += e
    ext = [x for x in all_ev if x["kind"] == "external"]
    assert ext == [{"kind": "external", "cells": [1], "forgot": [5, 9]}]
    assert [x for x in all_ev if x["kind"] == "unknown"] == [{"kind": "unknown", "cell": 5},
                                                                 {"kind": "unknown", "cell": 9}]
    assert m.memory(1) == ("Bubble", 1) and m.memory(5) is None and m.memory(9) is None
    assert m.memory(12) == ("Resonance", 2)  # readable cell keeps its memory
    assert (cell(eff, 5)["type"], cell(eff, 5)["src"]) == ("junk", "unknown")
    assert m.state(5) == "unknown"
    # the unknown events are emitted once, not every tick
    _, e = m.update(full(rd(1, "Bubble", 1), junk(5), junk(9)))
    assert e == []


def test_growth_self_change_not_external():
    m = CellMemory(CM)
    full = lambda a: board(c1=a, c5=rd(5, "Bubble", 1))
    for _ in range(2):
        m.update(full(rd(1, "Growth", 1)))
    m.update(full(rd(1, "Growth", 1)))
    m.update(board(c1=rd(1, "Growth", 1), c5=junk(5)))
    ev = []
    for _ in range(2):
        _, e = m.update(board(c1=rd(1, "Growth", 2), c5=junk(5)))
        ev += e
    assert m.memory(1) == ("Growth", 2) and m.memory(5) == ("Bubble", 1)
    assert [x for x in ev if x["kind"] in ("external", "unknown")] == []


def test_new_die_on_cell_without_memory_not_external():
    m = CellMemory(CM)
    ev = []
    for _ in range(3):
        _, e = m.update(board(c1=rd(1), c5=junk(5)))
        ev += e
    assert m.memory(1) == ("Resonance", 3)
    assert all(x["kind"] != "external" for x in ev)


def test_merged_and_supported_drop_memory_and_pending():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1), c2=rd(2, "Bubble", 1), c3=rd(3, "Adjust", 2)))
    m.update(board(c1=rd(1, "Bubble", 1)))  # pending on 1
    m.merged(1, 2)
    assert m.memory(1) is None and m.memory(2) is None and m.memory(3) == ("Adjust", 2)
    m.update(board(c1=rd(1, "Bubble", 1)))  # a pending count of 1 would have replaced; reset means it does not
    assert m.memory(1) is None
    m.supported(3)
    assert m.memory(3) is None
    eff, _ = m.update(board(c3=junk(3)))
    assert cell(eff, 3)["src"] == "unknown"


def test_no_effect_merge_keeps_memories():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1), c2=rd(2, "Bubble", 1)))
    m.own_action([1, 2])
    m.update(board(c1=junk(1), c2=junk(2)))  # merged() is not called
    assert m.memory(1) == ("Resonance", 3) and m.memory(2) == ("Bubble", 1)


def test_own_action_replacement_is_normal_update():
    m = CellMemory(CM)
    full = lambda a: board(c1=a, c5=rd(5, "Bubble", 1))
    for _ in range(2):
        m.update(full(rd(1, "Alignment", 2)))
    m.update(board(c1=rd(1, "Alignment", 2), c5=junk(5)))
    m.own_action([1], ticks=2)
    ev = []
    for _ in range(2):
        _, e = m.update(board(c1=rd(1, "Bubble", 1), c5=junk(5)))
        ev += e
    assert m.memory(1) == ("Bubble", 1) and m.memory(5) == ("Bubble", 1)
    assert [x for x in ev if x["kind"] in ("external", "unknown")] == []


def test_own_action_expired_replacement_is_external():
    m = CellMemory(CM)
    full = lambda a: board(c1=a, c5=rd(5, "Bubble", 1))
    for _ in range(2):
        m.update(full(rd(1, "Alignment", 2)))
    m.update(board(c1=rd(1, "Alignment", 2), c5=junk(5)))
    m.own_action([1], ticks=2)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2), c5=junk(5)))  # marks expire
    ev = []
    for _ in range(2):
        _, e = m.update(board(c1=rd(1, "Bubble", 1), c5=junk(5)))
        ev += e
    assert {"kind": "external", "cells": [1], "forgot": [5]} in ev and m.memory(5) is None


def test_supported_marks_own_action():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2), c5=rd(5, "Bubble", 1)))
    m.update(board(c1=rd(1, "Alignment", 2), c5=junk(5)))
    m.supported(1)
    ev = []
    for _ in range(2):
        _, e = m.update(board(c1=rd(1, "Bubble", 1), c5=junk(5)))
        ev += e
    assert m.memory(1) == ("Bubble", 1) and m.memory(5) == ("Bubble", 1) and ev == []


# ---- merge_verdict ----
B1, B2 = ("Resonance", 3), ("Bubble", 1)


def test_merge_verdict():
    same_f, same_t = rd(1), rd(2, "Bubble", 1)
    assert merge_verdict(same_f, same_t, B1, B2, CM) == "none"
    assert merge_verdict(junk(1), same_t, B1, B2, CM) == "undecided"
    assert merge_verdict(same_f, junk(2), B1, B2, CM) == "undecided"
    assert merge_verdict(junk(1), junk(2), B1, B2, CM) == "undecided"
    assert merge_verdict(rd(1, "empty", 0, 0.5), same_t, B1, B2, CM) == "undecided"
    assert merge_verdict(rd(1, "empty", 0, 0.99), junk(2), B1, B2, CM) == "effect"
    assert merge_verdict(same_f, rd(2, "Bubble", 2), B1, B2, CM) == "effect"
    assert merge_verdict(junk(1), rd(2, "Adjust", 1), B1, B2, CM) == "effect"
    assert merge_verdict(rd(1, "Resonance", 4), same_t, B1, B2, CM) == "effect"


# ---- bursts ----
def test_burst_needs_two_agreeing_confident_grabs():
    assert burst_result([rd(1)], CM) is None
    assert burst_result([rd(1), rd(1, "Bubble", 1)], CM) is None
    assert burst_result([rd(1), rd(1, conf=0.5), junk(1)], CM) is None
    assert burst_result([rd(1), junk(1), rd(1)], CM) == ("Resonance", 3)
    assert burst_result([rd(1), rd(1)], CM, agree=3) is None


def test_burst_empty_and_ties():
    e = lambda conf: rd(1, "empty", 0, conf)
    assert burst_result([e(0.95), e(0.97), junk(1)], CM) == ("empty", 0)
    assert burst_result([e(0.5), e(0.6)], CM) is None
    a = lambda conf: rd(1, "Alignment", 2, conf)
    b = lambda conf: rd(1, "Bubble", 1, conf)
    # highest single conf wins over group size
    assert burst_result([a(0.92), a(0.93), b(0.99), b(0.91)], CM) == ("Bubble", 1)
    # equal best conf -> larger group
    assert burst_result([a(0.95), b(0.95), b(0.91), a(0.9), b(0.92)], CM) == ("Bubble", 1)
    # equal conf and size -> earlier first read
    assert burst_result([b(0.95), a(0.95), a(0.95), b(0.95)], CM) == ("Bubble", 1)
    assert burst_result([a(0.95), b(0.95), b(0.95), a(0.95)], CM) == ("Alignment", 2)


def test_apply_burst_sets_memory():
    m = CellMemory(CM)
    eff, ev = m.apply_burst(4, ("Adjust", 5), {4})
    assert (eff["type"], eff["pip"], eff["src"]) == ("Adjust", 5, "burst")
    assert m.memory(4) == ("Adjust", 5) and m.state(4) == "remembered"
    assert ev == [{"kind": "remembered", "cell": 4, "tok": "Ad5"}]
    eff, _ = m.update(board(c4=junk(4)))  # still unreadable: memory read, no second event
    assert cell(eff, 4)["src"] == "memory"
    _, ev = m.update(board(c4=junk(4)))
    assert ev == []


def test_apply_burst_none_changes_nothing():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1)))
    before = (m.memory(1), m.state(1))
    assert m.apply_burst(1, None, {1}) == (None, [])
    assert (m.memory(1), m.state(1)) == before


def test_apply_burst_empty_drops_memory():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Growth", 1)))
    m.update(board(c1=junk(1)))
    eff, ev = m.apply_burst(1, ("empty", 0), {1})
    assert eff["type"] == "empty" and eff["src"] == "burst" and m.memory(1) is None
    assert ev == []  # Growth memory: not external


def test_apply_burst_replacement_is_external():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1, "Alignment", 2), c5=rd(5, "Bubble", 1)))
    m.update(board(c1=junk(1), c5=junk(5)))
    eff, ev = m.apply_burst(1, ("Bubble", 3), {1, 5})
    assert m.memory(1) == ("Bubble", 3) and m.memory(5) is None
    assert ev[0] == {"kind": "external", "cells": [1], "forgot": [5]}
    assert {"kind": "unknown", "cell": 5} in ev
    # same value as memory: no replacement
    m2 = CellMemory(CM)
    m2.apply_burst(1, ("Bubble", 3), {1})
    _, ev = m2.apply_burst(1, ("Bubble", 3), {1})
    assert ev == []
