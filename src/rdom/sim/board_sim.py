"""Offline placement simulator (M6, reduced scope).

Models the battle board to search for the placement method that uses the
FEWEST SKILL (Cheong destroy) casts -- the real bottleneck, since destroy has a
90s cooldown while summon and merge are free (no cooldown). Switch also has a
cooldown (secondary).

Operations (all types drawn uniformly, 20% each -- summon AND merge):
  summon  - a random-type die (pip 1) drops into a random empty cell   [free]
  swap    - Switch swapped with a same-pip die: the two cells exchange  [free*]
  merge   - two dice of the same (type,pip) -> ONE random-type die at   [free]
            pip+1 in one cell; the other cell frees. (Random Dice core.)
  destroy - Cheong removes a die; the cell frees.                       [SKILL]

Efficient skill use (user): two surplus dice -> merge them (frees 1 cell) ->
destroy the merged die (frees another) = TWO cells freed per one skill cast.

Pip matters only for Predator+Resonance (they must share one pip); we keep those
at pip 1 by only ever taking them from summon. Light/Bubble ignore pip.
"""
from __future__ import annotations
import random

DECK = ["Predator", "Light", "Resonance", "Bubble", "Switch"]
NCELLS = [4, 5, 9, 10, 13, 14, 15]
FIXED = {1: "Predator", 3: "Predator", 11: "Predator",
         2: "Light", 6: "Light", 7: "Light", 8: "Light", 12: "Light"}
NO_PIP = {"Light", "Bubble", "Switch"}   # pip irrelevant for these
# Predator placement priority (user, 2026-09-16): secure #1 first, then #11, #3.
PRED_PRIORITY = [1, 11, 3]


def disrupt(cells, k, rng):
    """Field-change effect: scramble k random occupied cells to a random deck
    type (pip kept). Returns a new cells list."""
    out = list(cells)
    occ = [i for i, c in enumerate(out) if c is not None]
    for i in rng.sample(occ, min(k, len(occ))):
        out[i] = (rng.choice(DECK), out[i][1])
    return out


class SimBoard:
    def __init__(self, seed=0, summon_weights=None):
        # cells[i] = (type, pip) or None
        self.cells = [None] * 15
        self.rng = random.Random(seed)
        self.weights = summon_weights or [1] * len(DECK)
        self.summons = 0
        self.merges = 0
        self.skills = 0        # destroy casts -- the metric to minimise

    def _draw(self):
        return self.rng.choices(DECK, weights=self.weights)[0]

    # -- operations -------------------------------------------------------
    def summon(self):
        empt = [i for i, c in enumerate(self.cells) if c is None]
        if not empt:
            return None
        i = self.rng.choice(empt)
        self.cells[i] = (self._draw(), 1)
        self.summons += 1
        return i

    def swap(self, i, j):
        self.cells[i], self.cells[j] = self.cells[j], self.cells[i]

    def merge(self, a, b):
        """Two same (type,pip) dice -> one random-type die at pip+1 in b; a frees.
        Returns the new type, or None if not mergeable."""
        ca, cb = self.cells[a], self.cells[b]
        if ca is None or cb is None or ca != cb:
            return None
        self.cells[a] = None
        self.cells[b] = (self._draw(), ca[1] + 1)
        self.merges += 1
        return self.cells[b][0]

    def destroy(self, i):
        self.cells[i] = None
        self.skills += 1

    # -- helpers ----------------------------------------------------------
    def full(self):
        return all(c is not None for c in self.cells)

    def empties(self):
        return [i for i, c in enumerate(self.cells) if c is None]


def is_complete(cells):
    """cells: 15-list of (type,pip)|None. Fixed cells right; n-cells hold >=1
    bubble (any pip) and >=3 resonance at the (single) predator pip. A Switch is
    NOT required for completion -- it can be removed once Predator/Light are set,
    but the bot keeps one as a recovery tool (see planner RESERVE_SWITCH)."""
    for cell, want in FIXED.items():
        c = cells[cell - 1]
        if c is None or c[0] != want:
            return False
    pred_pips = {cells[cell - 1][1] for cell in FIXED if FIXED[cell] == "Predator"}
    if len(pred_pips) != 1:
        return False
    p = next(iter(pred_pips))
    nt = [cells[c - 1] for c in NCELLS]
    bub = sum(1 for c in nt if c and c[0] == "Bubble")
    res_at_p = sum(1 for c in nt if c and c[0] == "Resonance" and c[1] == p)
    return bub >= 1 and res_at_p >= 3
