"""Rule engine (M3): decide the next action from the read board, following the
eager min-skill algorithm validated in simulation (docs/02).

Board = list of 15 dicts {cell,type,pip,...} from perception.board.read_board,
row-major, cell 1..15. The strategy is data, not learned.

Per tick we emit ONE action:
  summon              tap the summon button (game places a random pip-1 die)
  merge {from,to}     drag A onto B (same type+pip): reroll, frees a cell (free)
  destroy {cell}      drag to Cheong: frees a cell (SKILL, 90s cooldown)
  switch {from,to}    drag the Switch onto a same-pip die: swap positions (place)
"""
from __future__ import annotations

FIXED = {1: "Predator", 3: "Predator", 11: "Predator",
         2: "Light", 6: "Light", 7: "Light", 8: "Light", 12: "Light"}
NCELLS = [4, 5, 9, 10, 13, 14, 15]
NEED = {"Predator": 3, "Resonance": 3, "Light": 5, "Bubble": 1}
PIP1_ONLY = {"Predator", "Resonance"}      # must be pip 1 (alignment)
RESERVE_SWITCH = 1
PRED_PRIORITY = [1, 11, 3]                  # secure #1 first (docs/02)


def _by_cell(board):
    return {c["cell"]: c for c in board}


def _neighbors(cell):
    """Orthogonal neighbor cells (5x3 grid, row-major 1..15)."""
    r, c = (cell - 1) // 5, (cell - 1) % 5
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < 3 and 0 <= nc < 5:
            out.append(nr * 5 + nc + 1)
    return out


def evaluate(board):
    """{complete, violations[], pip_target}. Switch is not required to complete."""
    bc = _by_cell(board)
    v = []
    for cell, want in FIXED.items():
        got = bc[cell]["type"]
        if got != want:
            v.append({"kind": "wrong_type", "cell": cell, "want": want, "got": got})
    ntypes = [bc[c]["type"] for c in NCELLS]
    if ntypes.count("Bubble") < NEED["Bubble"]:
        v.append({"kind": "need_bubble", "have": ntypes.count("Bubble")})
    # resonance must share the predator pip
    pred_pips = [bc[c]["pip"] for c in (1, 3, 11) if bc[c]["type"] == "Predator"]
    p = pred_pips[0] if pred_pips and len(set(pred_pips)) == 1 else None
    res_ok = sum(1 for c in NCELLS
                 if bc[c]["type"] == "Resonance" and (p is None or bc[c]["pip"] == p))
    if res_ok < NEED["Resonance"]:
        v.append({"kind": "need_resonance", "have": res_ok, "need": NEED["Resonance"]})
    if pred_pips and len(set(pred_pips)) != 1:
        v.append({"kind": "pred_pip_split", "pips": pred_pips})
    return {"complete": not v, "violations": v, "pip_target": p}


def classify(board):
    """(keep set of cells, surplus list of cells, unmet dict). Reserves one
    pip-1 switch as a recovery tool (kept, not counted as a need)."""
    bc = _by_cell(board)
    desired = _desired(bc)
    unmet = dict(NEED)
    keep = set()
    for want in ("Predator", "Resonance", "Light", "Bubble"):
        # prefer keeping a die that already sits in a correct TARGET cell, so a
        # well-placed die is never demoted to surplus (and thus never merged or
        # destroyed) -- this stops the layout from churning while we fish.
        targets = [c for c in range(1, 16) if desired.get(c) == want]
        order = targets + [c for c in range(1, 16) if c not in targets]
        for cell in order:
            d = bc[cell]
            if cell in keep or d["type"] != want or unmet[want] <= 0:
                continue
            if want in PIP1_ONLY and d["pip"] != 1:
                continue
            keep.add(cell); unmet[want] -= 1
    reserved = 0
    for cell in range(1, 16):
        if reserved >= RESERVE_SWITCH:
            break
        if cell not in keep and bc[cell]["type"] == "Switch" and bc[cell]["pip"] == 1:
            keep.add(cell); reserved += 1
    surplus = [cell for cell in range(1, 16)
               if cell not in keep and bc[cell]["type"] != "empty"]
    return keep, surplus, unmet


def _surplus_pair(bc, surplus):
    """Two surplus cells that may be merged for fishing. NEVER merge Predator or
    Resonance (합성금지, user): merging them would create a pip-2 predator/resonance
    that violates the pip-1 rule and can never be arranged. Only Light/Bubble/Switch
    surplus is mergeable."""
    seen = {}
    for cell in surplus:
        if bc[cell]["type"] in PIP1_ONLY:      # never merge predator/resonance
            continue
        key = (bc[cell]["type"], bc[cell]["pip"])
        if key in seen:
            return seen[key], cell
        seen[key] = cell
    return None


def _mergeable_among(bc, cells):
    """Two occupied cells among `cells` with the same type+pip (mergeable)."""
    seen = {}
    for cell in cells:
        d = bc[cell]
        if d["type"] in ("empty", "Bomb", "Crystal"):
            continue
        key = (d["type"], d["pip"])
        if key in seen:
            return seen[key], cell
        seen[key] = cell
    return None


def _desired(bc):
    """Target type for each cell (None = don't care). n-cells: 1 bubble, 3
    resonance; the rest (incl. the roaming switch) are don't-care -- the switch
    reserve has no fixed home, it is just the blank tile used for arranging."""
    d = dict(FIXED)
    ncell = list(NCELLS)
    for want, k in (("Bubble", 1), ("Resonance", 3)):
        for _ in range(k):
            if ncell:
                d[ncell.pop(0)] = want
    return d


def _finalized(bc, desired):
    """Target cells that already hold the correct die (locked -- never moved and
    never cannibalised as a source). pip-1 types must also be at pip 1."""
    done = set()
    for cell, want in desired.items():
        d = bc[cell]
        if d["type"] == want and not (want in PIP1_ONLY and d["pip"] != 1):
            done.add(cell)
    return done


def _placement_swap(bc, locked=frozenset()):
    """One Switch swap toward the target layout, using the Switch as a blank tile.

    The arrangement is a partial permutation sort: for each unfinished target
    cell (priority order) find a source die of the needed type that is NOT itself
    in a finalised target cell, and move it in with the switch --
      * switch already on the target -> swap the needed die in (1 swap, done);
      * else walk the switch onto the target first (its wrong die spills onto the
        switch's old cell, which is never a finalised cell -> nothing correct is
        broken), and finish the placement next tick.
    A finalised cell is never a source and never a spill target, so the finalised
    set only grows: this converges in <=2 swaps per cell with no oscillation and
    no cannibalising of already-correct cells. Only swaps equal pips (the switch
    is pip 1, so everything it places is pip 1). Returns (from, to) or None (no
    swap helps -- inventory is short, let summon/merge/destroy create the type).

    `locked` cells (confirmed-correct fixed cells, tracked by the caller across
    frames) are treated as finalised REGARDLESS of the current read, so a die that
    reads wrong for a frame under the bubble effect is never swapped out -- this is
    what stops a correctly-placed Predator from being bounced away."""
    desired = _desired(bc)
    switches = [c for c in range(1, 16) if bc[c]["type"] == "Switch"]
    if not switches:
        return None
    sw = switches[0]
    done = _finalized(bc, desired) | set(locked)
    order = PRED_PRIORITY + [c for c in FIXED if c not in PRED_PRIORITY] + NCELLS
    for cell in order:
        want = desired.get(cell)
        if want is None or cell in done:
            continue
        need_pip1 = want in PIP1_ONLY
        # a source die of the needed type NOT already finalised elsewhere
        src = next((c for c in range(1, 16)
                    if c != cell and c not in done
                    and bc[c]["type"] == want
                    and (not need_pip1 or bc[c]["pip"] == 1)), None)
        if src is None:
            continue                          # short: summon/merge will create it
        # if a switch already sits on the target (possibly a 2nd/surplus switch),
        # use THAT one to place the die -- never swap switch<->switch (a no-op).
        sw_here = cell if bc[cell]["type"] == "Switch" else None
        if sw_here is not None:
            if bc[sw_here]["pip"] == bc[src]["pip"]:
                return (sw_here, src)         # place the needed die (finalises cell)
        else:
            if bc[sw]["pip"] == bc[cell]["pip"]:
                return (sw, cell)             # walk switch onto the target first
    return None


def plan_next(board, cheong_ready=True, switch_ready=True, locked=frozenset()):
    """One next action. ARRANGE first (switch a needed die into a wrong target
    cell), and only merge/destroy when nothing can be placed -- so the bot
    visibly builds the layout instead of merging indiscriminately. Switch is
    skipped while on cooldown (switch_ready=False) so it does not thrash. None
    when complete. `locked` = cells the caller has confirmed correct across frames;
    they are never disturbed even if the current frame misreads them."""
    ev = evaluate(board)
    bc = _by_cell(board)

    # 0) black bomb dice (special-effect only, disrupt placement) -> remove now.
    #    Bombs merge in pairs; an odd leftover is removed with the Cheong skill
    #    (user 2026-09-16).
    bombs = [c["cell"] for c in board if c["type"] == "Bomb"]
    if bombs:
        # Merging two bombs yields a pip-2 die (user), which breaks the pip-1 board
        # and desyncs the swap logic unless it's removed with Cheong. So clear bombs
        # ONLY with a skill and never leave a pip-2 leftover: pair -> merge+destroy,
        # lone bomb -> destroy. If Cheong is on cooldown, wait rather than merge into
        # an untracked pip-2 die.
        if not cheong_ready:
            return {"op": "wait", "why": "bombs present, cheong on cd"}
        if len(bombs) >= 2:
            return {"op": "merge_destroy", "from": bombs[0], "to": bombs[1],
                    "why": "bomb pair -> merge+destroy (pip2 removed)"}
        return {"op": "destroy", "cell": bombs[0], "why": "skill: leftover bomb"}

    # 0a) pip>=2 removal was DISABLED (2026-09-17): the live pip detector both
    #     FALSE-fired on good pip-1 predators (skill deleted a correctly-placed predator)
    #     and MISSED real pip-2 dice. Until pip detection is reliable enough to gate the
    #     skill, DO NOT act on `pip2` -- the skill stays bombs-only. See docs/07 pip work.

    # 0b) a "수정" (crystal) field structure clears after 7 merges in its
    #     up/down/left/right neighbours -> prioritise merging next to it.
    #     (Recognition of the crystal itself is TODO -- needs a live frame.)
    crystals = [c["cell"] for c in board if c["type"] == "Crystal"]
    if crystals:
        cr = crystals[0]
        pair = _mergeable_among(bc, _neighbors(cr))
        if pair:
            return {"op": "merge", "from": pair[0], "to": pair[1],
                    "why": "clear crystal (adjacent merge)"}
        return {"op": "summon", "why": "feed crystal-adjacent merges"}

    if ev["complete"]:
        return None

    # 1) place a die into a wrong target cell using the switch (priority:
    #    predator #1>#11>#3, then light, then n-cells). Only when off cooldown.
    if switch_ready:
        swap = _placement_swap(bc, locked)
        if swap:
            return {"op": "switch", "from": swap[0], "to": swap[1], "why": "arrange"}

    # 2) fill empty cells (live play: the summon thread already does this)
    empties = [c for c in range(1, 16) if bc[c]["type"] == "empty"]
    if empties:
        return {"op": "summon", "why": "fill the field"}

    # 3) board full, nothing to place -> free a cell to fish for the missing type.
    #    Keep the board pip-1 PURE (user 2026-09-17 chose this over plain merge, which
    #    left pip-2 dice that broke switch/merge). A plain merge is ~20% pip+1, so we
    #    MERGE the surplus pair then DESTROY the result with the skill -- no pip-2 ever
    #    remains, so switch swaps and merges always match pip and the board stays sortable.
    #    Cost: the skill is spent on fishing (a few casts/game, per sim); it is still
    #    there for bombs the rest of the time. NEVER merges predator/resonance (합성금지,
    #    enforced in _surplus_pair). A lone surplus with no pair -> destroy it (skill) to
    #    free one cell. No skill available -> wait rather than leave a pip-2 die.
    _, surplus, unmet = classify(board)
    if sum(unmet.values()) > 0 and cheong_ready:
        pair = _surplus_pair(bc, surplus)
        if pair:
            return {"op": "merge_destroy", "from": pair[0], "to": pair[1],
                    "why": "reroll: merge+destroy (keeps board pip1)"}
        if surplus:
            return {"op": "destroy", "cell": surplus[0], "why": "free a stuck cell"}
    return {"op": "wait", "why": "short inventory, cheong on cd" if unmet else "no move"}
