"""Support-deck rule engine (Resonance/Alignment/Bubble/Adjust/Growth). Pure functions, no I/O.

Board = 15 dicts {cell, type, pip}; cells row-major 1..15 on a 3x5 grid, column of cell c is
(c-1)%5+1. A merge frees `from` and turns `to` into a random die of the deck with pip+1.

Goal (complete): >= res7 Resonance pip 7, >= align7_min Alignment pip 7, Bubbles >= keep lo.
Merging continues after completion (pip 7 is never merged, so the targets are not lost).

Strategy:
  * Pip-7 dice and Growth are never merged; Adjust merges with any die of equal pip.
  * Highest pip first; Adjust is spent on Resonance/Alignment before Bubbles.
  * Bubbles: keep keep-lo..keep-hi; with more than keep-hi the merge must consume a Bubble.
  * Merges land in align_cols when possible (Alignment 7 forms there), else the smaller cell.
  * Supporter (reroll one die): Adjust 7, surplus Bubble, Resonance 7 beyond res7, lonely Adjust.

Actions: {"op": "summon"} | {"op": "merge", "from": c, "to": c}
         | {"op": "support", "from": c} | {"op": "wait", "why": str}
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

ROWS_N, COLS_N = 3, 5
MAX_PIP = 7


@dataclass(frozen=True)
class SupportDeck:
    dice: tuple = ("Resonance", "Alignment", "Bubble", "Adjust", "Growth")
    keep: dict = field(default_factory=lambda: {"Bubble": (2, 3, 3)})   # type -> (lo, hi, target)
    res7: int = 2
    align7_min: int = 3
    align_cols: tuple = (2, 3, 4)


DEFAULT = SupportDeck()


def load_support_deck(path):
    """Read [decks.support] from the deck file; a missing file, bad TOML or a missing
    table gives DEFAULT, a missing key keeps that key's default."""
    import tomllib
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, ValueError):
        return DEFAULT
    t = cfg.get("decks", {}).get("support")
    if not isinstance(t, dict):
        return DEFAULT
    deck = DEFAULT
    if "dice" in t:
        deck = replace(deck, dice=tuple(t["dice"]))
    if "keep" in t:
        deck = replace(deck, keep={k: (int(v[0]), int(v[1]), int(v[2] if len(v) > 2 else v[1]))
                                   for k, v in t["keep"].items()})
    if "res7" in t:
        deck = replace(deck, res7=int(t["res7"]))
    if "align7_min" in t:
        deck = replace(deck, align7_min=int(t["align7_min"]))
    if "align_cols" in t:
        deck = replace(deck, align_cols=tuple(int(c) for c in t["align_cols"]))
    return deck


def neighbors(cell):
    r, c = (cell - 1) // COLS_N, (cell - 1) % COLS_N
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS_N and 0 <= cc < COLS_N:
            out.append(rr * COLS_N + cc + 1)
    return out


def _col(cell):
    return (cell - 1) % COLS_N + 1


def _bubble_lo(deck):
    return deck.keep.get("Bubble", (0, 0, 0))[0]


def _bubble_hi(deck):
    return deck.keep.get("Bubble", (0, 99, 0))[1]


def evaluate_support(board, deck=DEFAULT):
    types = [d["type"] for d in board]
    ev = {
        "res7": sum(1 for d in board if d["type"] == "Resonance" and d["pip"] == MAX_PIP),
        "align7": sum(1 for d in board if d["type"] == "Alignment" and d["pip"] == MAX_PIP),
        "bubbles": types.count("Bubble"),
        "empty": types.count("empty"),
        "unknown": types.count("junk"),
        "bombs": [d["cell"] for d in board if d["type"] == "Bomb"],
        "crystals": [d["cell"] for d in board if d["type"] == "Crystal"],
    }
    ev["complete"] = (ev["res7"] >= deck.res7 and ev["align7"] >= deck.align7_min
                      and ev["bubbles"] >= _bubble_lo(deck))
    return ev


def can_merge_support(a, b):
    """Same type and pip 1..6, or an Adjust with any die of equal pip. Bombs merge with
    bombs and with a pip-1 Adjust (bombs carry no readable pip). Growth/Joker/Crystal/
    empty/junk and pip-7 dice never merge (policy)."""
    if a["cell"] == b["cell"]:
        return False
    if "Bomb" in (a["type"], b["type"]):
        o = b if a["type"] == "Bomb" else a
        return o["type"] == "Bomb" or (o["type"] == "Adjust" and o["pip"] == 1)
    ta, tb = a["type"], b["type"]
    if {"Growth", "Joker", "Crystal", "empty", "junk"} & {ta, tb}:
        return False
    if a["pip"] != b["pip"] or not 1 <= a["pip"] < MAX_PIP:
        return False
    return ta == tb or "Adjust" in (ta, tb)


def _merge_candidates(board, ev, deck, banned):
    """Ordered legal (from, to) pairs: not banned, no bomb, and the Bubbles the pair
    consumes must leave at least keep-lo."""
    lo = _bubble_lo(deck)
    out = []
    for a in board:
        for b in board:
            if ((a["cell"], b["cell"]) in banned or "Bomb" in (a["type"], b["type"])
                    or not can_merge_support(a, b)):
                continue
            used = (a["type"] == "Bubble") + (b["type"] == "Bubble")
            if used and ev["bubbles"] - used < lo:
                continue
            out.append((a, b))
    return out


def _bomb_action(board, banned, support_ready):
    """Bombs first: 1. bomb+bomb  2. bomb+Adjust(pip 1)  3. supporter."""
    bombs = [d for d in board if d["type"] == "Bomb"]
    if not bombs:
        return None
    for partner in ("Bomb", "Adjust"):
        for a in bombs:
            for b in board:
                if (b["type"] == partner and can_merge_support(a, b)
                        and (a["cell"], b["cell"]) not in banned):
                    return {"op": "merge", "from": a["cell"], "to": b["cell"]}
    if support_ready:
        return {"op": "support", "from": bombs[0]["cell"]}
    return None


def _joker_copy(board, ev, deck, banned):
    """Joker dragged onto a die of the same pip becomes that die's type: Alignment >
    Resonance > Bubble (only while Bubbles are short)."""
    score = {"Alignment": 10, "Resonance": 8}
    best = None
    for j in board:
        if j["type"] != "Joker" or j["pip"] <= 0:
            continue
        for d in board:
            if d["cell"] == j["cell"] or d["pip"] != j["pip"] or (j["cell"], d["cell"]) in banned:
                continue
            if d["type"] in score:
                sc = score[d["type"]]
            elif d["type"] == "Bubble" and ev["bubbles"] < _bubble_lo(deck):
                sc = 5
            else:
                continue
            key = (sc, -d["cell"])
            if best is None or key > best[0]:
                best = (key, j["cell"], d["cell"])
    return None if best is None else {"op": "merge", "from": best[1], "to": best[2]}


def _crystal_merge(cands, ev):
    """Every merge landing next to a Crystal chips it (landing cell counts). pip 1-2: land
    next to a crystal; pip 3+: move a crystal-adjacent die away from the crystals."""
    near = {n for c in ev["crystals"] for n in neighbors(c)}
    scored = []
    for a, b in cands:
        if a["pip"] <= 2 and b["cell"] in near:
            hits = sum(b["cell"] in neighbors(c) for c in ev["crystals"])
            scored.append((100 + hits * 10 - 0.5 * a["pip"], -b["cell"], a, b))
        elif a["pip"] >= 3 and a["cell"] in near and b["cell"] not in near:
            scored.append((50 + a["pip"], -b["cell"], a, b))
    if not scored:
        return None
    _, _, a, b = max(scored, key=lambda s: s[:2])
    return {"op": "merge", "from": a["cell"], "to": b["cell"]}


def _best_merge(cands, ev, deck):
    # AI-NOTE: surplus Bubbles (more than keep-hi) are merge fodder, so the merge must consume one
    if ev["bubbles"] > _bubble_hi(deck):
        with_bub = [p for p in cands if "Bubble" in (p[0]["type"], p[1]["type"])]
        cands = with_bub or cands

    def key(p):
        a, b = p
        # AI-NOTE: Adjust is worth more spent on Resonance/Alignment (raises their pip)
        # than on a Bubble, so an Adjust+Bubble pair loses the equal-pip tie.
        adj_pref = 0 if {a["type"], b["type"]} == {"Adjust", "Bubble"} else 1
        return (a["pip"], adj_pref, _col(b["cell"]) in deck.align_cols, -b["cell"])

    a, b = max(cands, key=key)
    return {"op": "merge", "from": a["cell"], "to": b["cell"]}


def _supporter_pick(board, ev, deck):
    """Supporter order: 1. Adjust 7  2. highest Bubble while > keep-hi  3. Resonance 7 beyond
    res7  4. Adjust 2..6 without a partner. Growth, Alignment and pip-1 dice are never picked."""
    def best(ds):
        return max(ds, key=lambda d: (d["pip"], -d["cell"]))["cell"] if ds else None

    c = best([d for d in board if d["type"] == "Adjust" and d["pip"] == MAX_PIP])
    if c:
        return c
    if ev["bubbles"] > _bubble_hi(deck):
        c = best([d for d in board if d["type"] == "Bubble" and d["pip"] >= 2])
        if c:
            return c
    if ev["res7"] > deck.res7:
        c = best([d for d in board if d["type"] == "Resonance" and d["pip"] == MAX_PIP])
        if c:
            return c
    return best([d for d in board if d["type"] == "Adjust" and 2 <= d["pip"] < MAX_PIP
                 and not any(can_merge_support(d, o) for o in board)])


def plan_support(board, deck=DEFAULT, support_ready=False, banned=frozenset(), clone_alert=False):
    """Next action. `banned` = (from, to) pairs that recently failed.

    clone_alert: a field effect will clone the highest die. The copy must be a Resonance/
    Alignment: a Bubble/Adjust/Joker above every one of them is rerolled with the supporter,
    and merges whose result (pip+1) could become the new maximum are held back."""
    ev = evaluate_support(board, deck)
    if ev["empty"]:
        return {"op": "summon"}
    if clone_alert:
        top = max((d["pip"] for d in board if d["type"] in ("Resonance", "Alignment")), default=0)
        rogue = [d for d in board if d["type"] in ("Bubble", "Adjust", "Joker") and d["pip"] > top]
        if rogue and support_ready:
            return {"op": "support", "from": max(rogue, key=lambda d: d["pip"])["cell"]}
        banned = set(banned) | {(a["cell"], b["cell"]) for a in board for b in board
                                if a["pip"] + 1 > top}
    act = _bomb_action(board, banned, support_ready)
    if act:
        return act
    act = _joker_copy(board, ev, deck, banned)
    if act:
        return act
    cands = _merge_candidates(board, ev, deck, banned)
    if cands:
        act = _crystal_merge(cands, ev) if ev["crystals"] else None
        return act or _best_merge(cands, ev, deck)
    if support_ready:
        cell = _supporter_pick(board, ev, deck)
        if cell:
            return {"op": "support", "from": cell}
    return {"op": "wait", "why": "complete" if ev["complete"] else "no move"}
