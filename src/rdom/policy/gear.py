"""Gear-deck rule engine (user's strategy, 2026-10-07). Pure functions, no I/O.

Board = 15 dicts {cell, type, pip} with type in Gear/Bubble/Adjust/Growth/Doom/
empty/junk (perception.gear.read_board). Cells are row-major 1..15 on a 3x5 grid.

Goal (complete): no empty cell, 1-3 Bubbles (2-3 preferred), every other die a Gear, all Gears
4-connected, mean Gear pip >= 2.2. Position does not matter.

Strategy:
  * Growth (성장) is never merged -- it changes by itself over time.
  * Doom (파멸) is merged whenever it has a partner (it would decay anyway).
  * Keep 2-3 Bubbles; surplus Bubbles are merge fodder.
  * Adjust (적응) merges with ANY die of the same pip.
  * Phase A (before 초월): fill the field, merge non-gears so the freed cell is next
    to the gear cluster and the merge result lands on the outside.
  * Phase B (after 초월): pip-1 gears and non-gears merge freely, gear pairs of
    pip >= 2 only while the gear average < 2. Complete -> no merges (maintain);
    one die from complete -> reroll that die with the supporter.
  * Supporter (서포터, 130 s cooldown): drag a die onto it -> pip-1 and a random type.
    Used on a non-gear die that blocks the gear cluster and has no merge partner.

Actions: {"op": "summon"} | {"op": "merge", "from": c, "to": c}
         | {"op": "support", "from": c} | {"op": "wait", "why": str}
"""
from __future__ import annotations

ROWS_N, COLS_N = 3, 5
MIN_BUBBLES, MAX_BUBBLES = 1, 3   # user 2026-10-08
TARGET_AVG = 2.2   # user 2026-10-08 (was 2.0)


def neighbors(cell):
    r, c = (cell - 1) // COLS_N, (cell - 1) % COLS_N
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS_N and 0 <= cc < COLS_N:
            out.append(rr * COLS_N + cc + 1)
    return out


def is_edge(cell):
    r, c = (cell - 1) // COLS_N, (cell - 1) % COLS_N
    return r in (0, ROWS_N - 1) or c in (0, COLS_N - 1)


def _bc(board):
    return {d["cell"]: d for d in board}


def gear_components(board):
    """Connected components (4-neighbour) of Gear cells, largest first."""
    bc = _bc(board)
    gears = {c for c, d in bc.items() if d["type"] == "Gear"}
    seen, comps = set(), []
    for g in sorted(gears):
        if g in seen:
            continue
        comp, stack = set(), [g]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(n for n in neighbors(x) if n in gears and n not in comp)
        seen |= comp
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def evaluate(board):
    bc = _bc(board)
    types = [d["type"] for d in board]
    gears = [d for d in board if d["type"] == "Gear"]
    comps = gear_components(board)
    n_bub = types.count("Bubble")
    others = [d["cell"] for d in board if d["type"] not in ("Gear", "Bubble", "Crystal")]
    bombs = [d["cell"] for d in board if d["type"] == "Bomb"]
    crystals = [d["cell"] for d in board if d["type"] == "Crystal"]
    avg = sum(d["pip"] for d in gears) / len(gears) if gears else 0.0
    ev = {
        "gears": len(gears), "bubbles": n_bub, "others": others, "crystals": crystals, "bombs": bombs,
        "empty": types.count("empty"), "unknown": types.count("junk"),
        "largest_cluster": len(comps[0]) if comps else 0,
        "connected": len(comps) <= 1, "gear_avg": round(avg, 2),
    }
    ev["complete"] = (ev["unknown"] == 0 and not others and not crystals and not bombs
                      and MIN_BUBBLES <= n_bub <= MAX_BUBBLES
                      and ev["connected"] and avg >= TARGET_AVG)
    return ev


def pip_options(d):
    """Pips a die may really have. Doom used to be hedged (read 2 -> 2 or 3) on the
    belief that its countdown number hides the centre pip; it does not -- the centre
    pip is drawn ON TOP of the number (2026-10-09), so every die reads exactly."""
    return (d["pip"],)


def can_merge(a, b):
    """Merge legality: same type and pip, or an Adjust with any die of equal pip.
    Bombs merge with bombs and with a pip-1 Adjust (user 2026-10-09; bombs carry no
    readable pip). Growth is excluded by policy (user), not by the game."""
    if a["cell"] == b["cell"]:
        return False
    if "Bomb" in (a["type"], b["type"]):
        o = b if a["type"] == "Bomb" else a
        return o["type"] == "Bomb" or (o["type"] == "Adjust" and o["pip"] == 1)
    if a["pip"] <= 0 or b["pip"] <= 0:
        return False
    if not set(pip_options(a)) & set(pip_options(b)):
        return False
    ta, tb = a["type"], b["type"]
    if {"Growth", "empty", "junk", "Crystal", "Joker"} & {ta, tb}:
        return False
    return ta == tb or "Adjust" in (ta, tb)


def _gear_adj(bc, cell):
    return sum(1 for n in neighbors(cell) if bc[n]["type"] == "Gear")


def _fodder_ok(d, n_bub, allow_gear):
    """May this die be consumed by a merge?"""
    t = d["type"]
    if t == "Growth":
        return False
    if t == "Bubble":
        return n_bub > MAX_BUBBLES
    if t == "Gear":
        return allow_gear
    return True                                  # Doom, Adjust


def _merge_candidates(board, allow_gear, banned):
    bc = _bc(board)
    n_bub = sum(1 for d in board if d["type"] == "Bubble")
    out = []
    for a in board:
        for b in board:
            if (a["cell"], b["cell"]) in banned or not can_merge(a, b):
                continue
            if not (_fodder_ok(a, n_bub, allow_gear) and _fodder_ok(b, n_bub, allow_gear)):
                continue
            out.append((a, b))
    return bc, out


def _score_phase_a(bc, a, b):
    """Merge a -> b. a's cell is freed (a new random die will be summoned somewhere),
    b becomes a random die with pip+1. Free cells next to the gear cluster, put the
    random result away from it (outer ring)."""
    s = 2.0 * _gear_adj(bc, a["cell"]) - 2.0 * _gear_adj(bc, b["cell"])
    s += 1.0 if is_edge(b["cell"]) else 0.0
    s -= 0.5 if is_edge(a["cell"]) else 0.0
    if "Doom" in (a["type"], b["type"]):
        s += 3.0                                   # Doom decays anyway: use it first
    if a["type"] == "Gear" or b["type"] == "Gear":
        s -= 10.0
    return s


def _phase_b_allowed(a, b, avg):
    """User rule 2026-10-07 (after a fully aggressive run dropped the field from 13
    to 9 gears): pip-1 gears and non-gears merge freely; gear pairs of pip >= 2
    only while the gear average is below TARGET_AVG."""
    if a["type"] != "Gear" and b["type"] != "Gear":
        return True
    return a["pip"] == 1 or avg < TARGET_AVG


def _score_phase_b(bc, a, b, avg):
    """Lower pips first (raises the gear average fastest); non-gear fodder before gears."""
    s = -1.5 * a["pip"]
    if "Doom" in (a["type"], b["type"]):
        s += 3.0
    if a["type"] != "Gear" and b["type"] != "Gear":
        s += 2.0
    # keep the cluster connected: prefer freeing a cell that touches gears
    s += 0.5 * _gear_adj(bc, a["cell"])
    return s


def _bridge_bubble(board, ev):
    """A gear group is cut off (2026-10-07 live: a gear walled in by two bubbles,
    bot idled for minutes). The bubble touching the most separate gear groups --
    the one standing between them -- to reroll with the supporter, or None."""
    if ev["connected"] or ev["bubbles"] <= MIN_BUBBLES:
        return None
    comp_of = {c: i for i, comp in enumerate(gear_components(board)) for c in comp}
    best = None
    for d in board:
        if d["type"] != "Bubble":
            continue
        groups = {comp_of[n] for n in neighbors(d["cell"]) if n in comp_of}
        if len(groups) >= 2 and (best is None or len(groups) > best[0]):
            best = (len(groups), d["cell"])
    return best[1] if best else None


def defects(board, ev=None):
    """Cells keeping a full, gear-avg-OK field from being complete: non-gear
    non-bubble dice plus surplus bubbles. (Disconnection is handled by
    _bridge_bubble.)"""
    ev = ev or evaluate(board)
    out = list(ev["others"])
    bub = [d["cell"] for d in board if d["type"] == "Bubble"]
    if len(bub) > MAX_BUBBLES:
        out += sorted(bub, key=lambda c: next(d["pip"] for d in board if d["cell"] == c))[
            :len(bub) - MAX_BUBBLES]
    return out


def near_complete(board, ev=None):
    """One die short of complete: full, readable, connected, avg OK, one defect."""
    ev = ev or evaluate(board)
    return (not ev["complete"] and ev["empty"] == 0 and ev["unknown"] == 0 and not ev["crystals"]
            and ev["connected"] and ev["gear_avg"] >= TARGET_AVG
            and len(defects(board, ev)) == 1)


def _max_gear_pip(board):
    return max((d["pip"] for d in board if d["type"] == "Gear"), default=0)


def _joker_copy(board, ev, banned):
    """Joker (조커, pink crown): dragged onto a die of the same pip it turns into
    that die's type (user 2026-10-08). Copy a gear whenever one matches -- one more
    gear for free. Otherwise copy a bubble only while bubbles are short."""
    jokers = [d for d in board if d["type"] == "Joker" and d["pip"] > 0]
    best = None
    for j in jokers:
        for d in board:
            if d["cell"] == j["cell"] or (j["cell"], d["cell"]) in banned or d["pip"] <= 0:
                continue
            if not set(pip_options(j)) & set(pip_options(d)):
                continue
            if d["type"] == "Gear":
                sc = 10 + sum(n["type"] == "Gear" for n in [_bc(board)[c] for c in neighbors(j["cell"])])
            elif d["type"] == "Bubble" and ev["bubbles"] < MIN_BUBBLES:
                sc = 5
            else:
                continue
            if best is None or sc > best[0]:
                best = (sc, j["cell"], d["cell"])
    return None if best is None else {"op": "merge", "from": best[1], "to": best[2]}


def _bomb_action(board, ev, banned, support_ready):
    """Bombs (field effect, at game start or on a merge) are cleared first, in the
    user's order (2026-10-09): 1. bomb+bomb  2. bomb+Adjust(pip 1)  3. supporter."""
    bombs = [d for d in board if d["type"] == "Bomb"]
    if not bombs:
        return None
    for partner_type in ("Bomb", "Adjust"):
        for a in bombs:
            for b in board:
                if (b["cell"] != a["cell"] and b["type"] == partner_type
                        and (partner_type == "Bomb" or b["pip"] == 1) and (a["cell"], b["cell"]) not in banned):
                    return {"op": "merge", "from": a["cell"], "to": b["cell"]}
    if support_ready:
        return {"op": "support", "from": bombs[0]["cell"]}
    return None


def _crystal_merge(board, ev, transcended, banned):
    """Crystal (수정, HP 700): every merge in one of its 4 neighbours takes 100 off
    (user 2026-10-08). The merge counts at its LANDING cell (`to`, user confirmed),
    so only merges landing next to a crystal are chosen here.
    Before 초월 gears are still not merged; after it any legal pair may be used."""
    near = {n for c in ev["crystals"] for n in neighbors(c)}
    bc, cands = _merge_candidates(board, allow_gear=transcended, banned=banned)
    scored = []
    for a, b in cands:
        if b["cell"] in near:
            hits = sum(b["cell"] in neighbors(c) for c in ev["crystals"])   # touches 2 crystals?
            pen = 3 * (a["type"] == "Gear") + 3 * (b["type"] == "Gear") + 0.5 * a["pip"]
            scored.append((hits * 10 - pen, a, b))
    if not scored:
        return None
    _, a, b = max(scored, key=lambda x: x[0])
    return {"op": "merge", "from": a["cell"], "to": b["cell"]}


def plan_next(board, transcended=False, support_ready=False, banned=frozenset(),
              clone_alert=False):
    """Next action for the board. `banned` = (from, to) pairs that recently failed
    (the merge did not change the board -> recognition was wrong).

    clone_alert: the field effect "N초 후 낮은 눈금 3개 파괴 + 최고 눈금 주사위 1개 복제"
    is counting down. The copy must be a gear: a non-gear die above every gear is
    rerolled with the supporter, and merges whose result (pip+1, random type) could
    become the new maximum are held back."""
    ev = evaluate(board)
    if clone_alert:
        top = _max_gear_pip(board)
        rogue = [d for d in board if d["type"] not in ("Gear", "empty", "junk") and d["pip"] > top]
        if rogue and support_ready:
            return {"op": "support", "from": max(rogue, key=lambda d: d["pip"])["cell"]}
        banned = set(banned) | {(a["cell"], b["cell"]) for a in board for b in board
                                if a["pip"] + 1 > top}
    if ev["complete"] and not transcended:
        return {"op": "wait", "why": "complete"}
    if ev["empty"]:
        return {"op": "summon"}
    act = _bomb_action(board, ev, banned, support_ready)
    if act:
        return act
    act = _joker_copy(board, ev, banned)
    if act:
        return act
    if ev["crystals"]:
        act = _crystal_merge(board, ev, transcended, banned)
        if act:
            return act

    if not transcended:
        bc, cands = _merge_candidates(board, allow_gear=False, banned=banned)
        if cands:
            a, b = max(cands, key=lambda p: _score_phase_a(bc, *p))
            return {"op": "merge", "from": a["cell"], "to": b["cell"]}
    else:
        # complete or one die away: finish/keep it with the supporter, never merge
        # (a merge result is random and would break the field) -- user 2026-10-07
        if ev["complete"]:
            return {"op": "wait", "why": "complete (maintain)"}
        if near_complete(board, ev):
            if support_ready:
                return {"op": "support", "from": defects(board, ev)[0]}
            return {"op": "wait", "why": "near-complete: supporter cooldown"}
        bridge = _bridge_bubble(board, ev) if support_ready else None
        if bridge:
            return {"op": "support", "from": bridge}
        # after 초월 merges come out as gears with very high probability (user
        # 2026-10-07: "더 과감하게 합성해도 좋아") -> gear merges always allowed,
        # also once the field is complete: higher pips, same layout.
        bc, cands = _merge_candidates(board, allow_gear=True, banned=banned)
        cands = [p for p in cands if _phase_b_allowed(*p, ev["gear_avg"])]
        if cands:
            a, b = max(cands, key=lambda p: _score_phase_b(bc, *p, ev["gear_avg"]))
            return {"op": "merge", "from": a["cell"], "to": b["cell"]}

    if ev["complete"]:
        return {"op": "wait", "why": "complete"}
    if support_ready:
        bc = _bc(board)
        n_bub = ev["bubbles"]
        pool = [d for d in board if d["type"] in ("Doom", "Adjust")
                or (d["type"] == "Bubble" and n_bub > MAX_BUBBLES)]
        if pool:
            d = max(pool, key=lambda d: (_gear_adj(bc, d["cell"]), d["pip"]))
            return {"op": "support", "from": d["cell"]}
    return {"op": "wait", "why": "no move"}

