"""Placement planners for the sim, optimised for FEWEST SKILL (destroy) casts.

Merge is a free reroll (two dice -> one random-type die, one cell freed), so
cells can be freed without any skill; a merge that lands on a needed Light or
Bubble is pure profit. Destroy (the 90s-cooldown skill) is used only when no
surplus pair can be merged. Three "don't-care" n-cells park junk for free.
"""
from __future__ import annotations
from .board_sim import SimBoard, DECK, FIXED, NCELLS

# Completion needs 12 dice (Predator/Light/Resonance/Bubble). A Switch is not
# required to complete, but the bot RESERVES one pip-1 switch as a recovery tool
# for later field-change disruptions (user's recommendation). It sits in one of
# the 3 don't-care cells, so only 2 cells are truly free-for-junk.
NEED = {"Predator": 3, "Resonance": 3, "Light": 5, "Bubble": 1}
RESERVE_SWITCH = 1
PIP1_ONLY = {"Predator", "Resonance"}   # must be pip 1
PARK = 2


def classify(cells):
    """Greedily assign dice to needs, plus reserve one pip-1 switch as a keep.
    Predator/Resonance count only at pip 1; Light/Bubble any pip. Returns
    (keep set, surplus list, unmet dict). unmet excludes the reserved switch."""
    unmet = dict(NEED)
    keep = set()
    order = ["Predator", "Resonance", "Light", "Bubble"]
    for want in order:
        for i, c in enumerate(cells):
            if i in keep or c is None:
                continue
            if unmet[want] <= 0:
                break
            t, pip = c
            if t != want:
                continue
            if want in PIP1_ONLY and pip != 1:
                continue
            keep.add(i)
            unmet[want] -= 1
    # reserve one pip-1 switch (kept, not counted in unmet)
    reserved = 0
    for i, c in enumerate(cells):
        if reserved >= RESERVE_SWITCH:
            break
        if i not in keep and c is not None and c[0] == "Switch" and c[1] == 1:
            keep.add(i)
            reserved += 1
    surplus = [i for i, c in enumerate(cells) if c is not None and i not in keep]
    return keep, surplus, unmet


def _same_pair(cells, idxs):
    seen = {}
    for i in idxs:
        k = cells[i]
        if k in seen:
            return seen[k], i
        seen[k] = i
    return None


def solve(board: SimBoard, mode="min_skill", max_steps=5000):
    """Run until the inventory satisfies the target (switch arrangement is free).
    modes:
      destroy_only - free cells by destroy (skill) only (baseline)
      min_skill    - when full, merge a surplus pair (free reroll) else destroy
      eager        - merge surplus pairs as soon as available (front-load rerolls),
                     summon into empties, destroy only when stuck
    """
    for _ in range(max_steps):
        keep, surplus, unmet = classify(board.cells)
        if sum(unmet.values()) == 0:
            _realize(board)
            break
        pair = _same_pair(board.cells, surplus)
        if mode == "eager" and pair:
            board.merge(*pair)               # reroll now, free a cell
            continue
        if not board.full():
            board.summon()
            continue
        if mode == "destroy_only":
            board.destroy(surplus[0])
        else:                                # min_skill / eager when full
            if pair:
                board.merge(*pair)           # free a cell, no skill
            else:
                board.destroy(surplus[0])    # forced skill
    return {
        "complete_inventory": sum(classify(board.cells)[2].values()) == 0,
        "skills": board.skills,
        "summons": board.summons,
        "merges": board.merges,
    }


def _realize(board):
    """Place a valid target layout so is_complete passes (arrangement is free)."""
    cells = [None] * 15
    src = list(board.cells)

    def take(pred):
        for i, c in enumerate(src):
            if c is not None and pred(c):
                src[i] = None
                return c
        return None

    for cell, want in FIXED.items():
        if want == "Predator":
            cells[cell - 1] = take(lambda c: c[0] == "Predator" and c[1] == 1)
        else:
            cells[cell - 1] = take(lambda c: c[0] == "Light")
    ncell = list(NCELLS)
    cells[ncell.pop(0) - 1] = take(lambda c: c[0] == "Bubble")
    for _ in range(3):
        cells[ncell.pop(0) - 1] = take(lambda c: c[0] == "Resonance" and c[1] == 1)
    # keep a reserved switch in a don't-care cell if we have one (recovery tool)
    sw = take(lambda c: c[0] == "Switch" and c[1] == 1)
    if sw is not None:
        cells[ncell.pop(0) - 1] = sw
    leftovers = [c for c in src if c is not None]
    for cpos in ncell:
        cells[cpos - 1] = leftovers.pop() if leftovers else ("Resonance", 1)
    board.cells = cells
