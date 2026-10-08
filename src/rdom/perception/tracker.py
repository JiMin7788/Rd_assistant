"""Per-cell belief tracker (docs/07 Layer A).

The own board is a slowly-changing state: a cell only changes when the bot summons
(fills an empty cell), swaps/merges/destroys it, a field effect transforms it, or a
bomb lands. Yet every frame was classified from scratch, so a single effect frame
(glow wash, colour-cast buff, pink glitch, buff arrows, predator digits) produced a
wrong read and a wrong action.

This tracker turns "classify each frame" into "update a per-cell belief":
  - a LOW-confidence observation is ignored (abstain) -- the belief is kept;
  - a HIGH-confidence observation that AGREES reinforces the belief;
  - a HIGH-confidence observation that DISAGREES only overturns the belief after the
    SAME new type is seen K frames in a row (K large for a correct fixed cell, so a
    correctly-placed Predator is never yanked by a burst of effect frames);
  - it is ACTION-AWARE: after a switch the two beliefs swap and accept the next frame
    immediately; after a merge/destroy the freed cell becomes empty; a die appearing
    on an empty cell (a summon) is accepted at once.

`plan_next` then runs on `belief_board()` with `uncertain()` cells locked, so the bot
only ever acts on beliefs that survived several clean observations. This generalizes
the old `locked`/`wrongrun` logic in bot_live.py to all 15 cells.
"""
from __future__ import annotations

from rdom.policy.target import FIXED   # {cell: required type} for the 8 fixed cells

ABSTAIN = 0.50        # observation conf below this -> ignore the frame (effect frame)
CONF_FLOOR = 0.50     # belief conf below this -> the cell is "uncertain" (not moved)
K_NORMAL = 3          # frames of a stable new type needed to change a normal belief
K_PROTECT = {"Predator": 8, "Light": 5}   # harder to abandon a CORRECT fixed cell


class CellTracker:
    def __init__(self):
        self.belief = {c: None for c in range(1, 16)}   # type str, or None if unseen
        self.conf = {c: 0.0 for c in range(1, 16)}
        self.age = {c: 0 for c in range(1, 16)}         # frames since last real update
        self._pending = {c: None for c in range(1, 16)}  # (candidate_type, streak)
        self._k1 = set()                                 # cells to accept in 1 frame next
        self.pip2 = {c: False for c in range(1, 16)}    # believe the die is pip>=2
        self._pip2run = {c: 0 for c in range(1, 16)}    # consecutive pip2 observations

    PIP2_K = 3      # pip2 must be seen this many confident frames before we believe it
                    # (a merge/effect can flash a miscount; the skill must not fire on one)

    # -- K (frames-to-change) for a proposed new type on a cell ------------------
    def _k(self, cell, new_type):
        if cell in self._k1:                 # just swapped -> trust the next read
            return 1
        if new_type == "Bomb":               # a bomb replaces a die and must be cleared;
            return 2                          # 2 frames = prompt but filters one dark blip
        if self.belief[cell] == "empty":     # a die appearing on an empty cell = summon
            return 1
        cur = self.belief[cell]
        if cell in FIXED and cur == FIXED[cell] and new_type != cur:
            return K_PROTECT.get(cur, K_NORMAL)   # never yank a correct fixed cell fast
        return K_NORMAL

    # -- apply the effect of the action we JUST performed ------------------------
    def _apply_action(self, act):
        if not act:
            return
        op = act.get("op")
        if op == "switch":
            f, t = act.get("from"), act.get("to")
            if f in self.belief and t in self.belief:
                self.belief[f], self.belief[t] = self.belief[t], self.belief[f]
                self.conf[f], self.conf[t] = self.conf[t], self.conf[f]
                self.pip2[f], self.pip2[t] = self.pip2[t], self.pip2[f]
                self._pip2run[f], self._pip2run[t] = self._pip2run[t], self._pip2run[f]
                self._pending[f] = self._pending[t] = None
                self._k1 = {f, t}            # confirm/repair from the next frame
        elif op in ("merge", "merge_destroy"):
            self._free(act.get("from"))
            if op == "merge_destroy":
                self._free(act.get("to"))
        elif op == "destroy":
            self._free(act.get("cell"))

    def _free(self, c):
        """A cell we just emptied (merge/destroy): reset belief and pip2."""
        if c in self.belief:
            self.belief[c] = "empty"; self.conf[c] = 0.4; self._pending[c] = None
            self.pip2[c] = False; self._pip2run[c] = 0

    # -- fold a frame's 15 observations into the beliefs ------------------------
    def update(self, observations, last_action=None):
        """observations: iterable of {cell, type, conf}. `last_action` is the action
        performed since the previous update (or None). Returns self."""
        self._apply_action(last_action)
        k1_this = self._k1                    # applies only to THIS frame
        self._k1 = set()
        for o in observations:
            c = o["cell"]
            t = o["type"]
            p = float(o.get("conf", o.get("score", 1.0)))
            if p < ABSTAIN or t == "unknown":     # effect frame -> keep belief
                self.age[c] += 1
                continue
            cur = self.belief[c]
            changed = False
            if cur is None:                       # first confident sighting
                self.belief[c] = t; self.conf[c] = p; self._pending[c] = None; self.age[c] = 0
                changed = True
            elif t == cur:                        # agrees -> reinforce
                self.conf[c] = min(1.0, self.conf[c] + p * 0.5)
                self._pending[c] = None; self.age[c] = 0
            else:                                 # disagrees -> need a stable streak
                pend = self._pending[c]
                pend = (t, pend[1] + 1) if (pend and pend[0] == t) else (t, 1)
                self._pending[c] = pend
                need = 1 if c in k1_this else self._k(c, t)
                if pend[1] >= need:
                    self.belief[c] = t; self.conf[c] = p
                    self._pending[c] = None; self.age[c] = 0
                    changed = True
            # pip>=2 belief: a new die (type changed) starts pip-1; otherwise require
            # PIP2_K confident pip2 frames in a row before believing it, and any clean
            # pip1 read clears it. This keeps the skill from firing on a one-frame miscount.
            if changed:
                self.pip2[c] = False; self._pip2run[c] = 0
            elif o.get("pip2"):
                self._pip2run[c] += 1
                if self._pip2run[c] >= self.PIP2_K:
                    self.pip2[c] = True
            else:
                self._pip2run[c] = 0; self.pip2[c] = False
        return self

    # -- outputs for the planner -----------------------------------------------
    def belief_board(self):
        """15 cell dicts {cell, type, pip, score}; an unseen/unknown cell reads empty
        (nothing confident to act on there yet)."""
        out = []
        for c in range(1, 16):
            b = self.belief[c]
            if b in (None, "unknown"):
                b = "empty"
            pip2 = self.pip2[c] and b not in ("empty", "Switch")
            out.append({"cell": c, "type": b, "pip": 0 if b == "empty" else 1,
                        "pip2": pip2, "score": round(self.conf[c], 3)})
        return out

    def uncertain(self, floor=CONF_FLOOR):
        """Cells the planner must NOT touch: unseen, or belief below the confidence
        floor. Passed to plan_next as part of `locked`."""
        return frozenset(c for c in range(1, 16)
                         if self.belief[c] in (None, "unknown") or self.conf[c] < floor)

    def confidence(self, cell):
        return self.conf[cell]
