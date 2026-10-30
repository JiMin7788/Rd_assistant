"""Per-cell memory for the support deck: the effective board for hacked / unreadable cells.

Pure (no cv2, torch, I/O). A hacked die keeps its type and pip but reads as junk, so the last confirmed value
is kept until the cell really changes (spec rdF02 R6, R7). Reads are dicts {cell, type, variant, pip, conf}.

Effective reads carry src: 'read' (raw), 'memory', 'burst', 'unknown'.
"""

import math

GROWTH = "Growth"
EMPTY = "empty"
JUNK = "junk"


def _finite(x):
    try:
        return math.isfinite(x)
    except TypeError:
        return False


def _unreadable(d, conf_min, empty_conf_min=0.0):
    # AI-NOTE: a NaN conf makes `conf < conf_min` False, which would read as confident; a non-finite conf is unreadable
    # AI-NOTE: empty_conf_min is passed in (callers give support.EMPTY_CONF_MIN) so this module stays pure; a white
    # flash can read as a confident empty, so an 'empty' read needs the stricter cut. 0.0 = no extra cut.
    if d["type"] == JUNK or not _finite(d["conf"]) or d["conf"] < conf_min:
        return True
    return d["type"] == EMPTY and d["conf"] < empty_conf_min


def _value(d):
    return (d["type"], d["pip"])


def _tok(value):
    return "%s%d" % (value[0][:2], value[1])


def _eff(d, typ, pip, src):
    e = dict(d)
    e.update(type=typ, variant=typ, pip=pip, src=src)
    return e


class CellMemory:
    def __init__(self, conf_min, confirm=2, empty_conf_min=0.0):
        self.conf_min = conf_min
        self.empty_conf_min = empty_conf_min
        self.confirm = confirm
        self._mem = {}      # cell -> (type, pip)
        self._pend = {}     # cell -> (value, count); value may be ("empty", 0)
        self._own = {}      # cell -> update() calls left marked own-action
        self._state = {}    # cell -> "readable" | "remembered" | "unknown"
        self._conf = {}     # cell -> last raw conf (used for burst reads)

    # ---- queries ----
    def unreadable(self, d):
        return _unreadable(d, self.conf_min, self.empty_conf_min)

    def memory(self, cell):
        return self._mem.get(cell)

    def state(self, cell):
        return self._state.get(cell, "readable")

    # ---- own actions ----
    def own_action(self, cells, ticks=5):
        for c in cells:
            self._own[c] = ticks

    def _drop(self, cell):
        self._mem.pop(cell, None)
        self._pend.pop(cell, None)
        if self._state.get(cell) == "remembered":
            self._state[cell] = "unknown"

    def merged(self, fr, to):
        self._drop(fr)
        self._drop(to)

    def supported(self, cell):
        self._drop(cell)
        self.own_action([cell])

    # ---- per-tick update ----
    def update(self, raw):
        """15 raw reads -> (effective board, events). Call once per board tick."""
        events = []
        changed = []
        for i, d in enumerate(raw):
            c = d.get("cell", i + 1)
            self._conf[c] = d["conf"]
            if self.unreadable(d):
                continue  # pending stays: an unreadable tick says nothing about the die
            mem = self._mem.get(c)
            val = _value(d) if d["type"] != EMPTY else (EMPTY, 0)
            if val == mem or (val[0] == EMPTY and mem is None):
                self._pend.pop(c, None)
                continue
            pv, n = self._pend.get(c, (None, 0))
            n = n + 1 if pv == val else 1
            if n < self.confirm:
                self._pend[c] = (val, n)
                continue
            self._pend.pop(c, None)
            if mem is not None and mem[0] != GROWTH and self._own.get(c, 0) <= 0:
                changed.append(c)  # AI-NOTE: Growth grows by itself and own-action cells change by us
            if val[0] == EMPTY:
                self._mem.pop(c, None)
            else:
                self._mem[c] = val
        unread = [d.get("cell", i + 1) for i, d in enumerate(raw) if self.unreadable(d)]
        if changed:
            events.extend(self._external(changed, unread))
        eff = []
        for i, d in enumerate(raw):
            c = d.get("cell", i + 1)
            if not self.unreadable(d):
                self._state[c] = "readable"
                eff.append(_eff(d, d["type"], d["pip"], "read"))
                continue
            mem = self._mem.get(c)
            if mem is None:
                self._state[c] = "unknown"
                eff.append(_eff(d, JUNK, 0, "unknown"))
                continue
            if self._state.get(c) != "remembered":
                events.append({"kind": "remembered", "cell": c, "tok": _tok(mem)})
            self._state[c] = "remembered"
            eff.append(_eff(d, mem[0], mem[1], "memory"))
        for c in list(self._own):
            self._own[c] -= 1
            if self._own[c] <= 0:
                del self._own[c]
        return eff, events

    def _external(self, changed, unreadable_cells):
        """R7.4: forget every cell unreadable now; returns [external event, unknown events...]."""
        forgot = []
        for c in sorted(unreadable_cells):
            if c in changed:
                continue
            if c in self._mem:
                forgot.append(c)
            self._drop(c)
        return ([{"kind": "external", "cells": sorted(changed), "forgot": forgot}]
                + [{"kind": "unknown", "cell": c} for c in forgot])

    # ---- burst ----
    def apply_burst(self, cell, value, unreadable_cells):
        """Accepted burst value (type, pip) or None -> (effective read or None, events)."""
        if value is None:
            return None, []
        events = []
        mem = self._mem.get(cell)
        raw = {"cell": cell, "conf": self._conf.get(cell, 0.0)}
        self._pend.pop(cell, None)
        # R7.3/R7.4 apply to a burst value that differs from the memory (the burst already is the 2-grab confirmation)
        replaced = (mem is not None and mem != value and mem[0] != GROWTH
                    and self._own.get(cell, 0) <= 0)
        others = set(unreadable_cells) - {cell}
        if value[0] == EMPTY:
            self._mem.pop(cell, None)
            self._state[cell] = "unknown"
            if replaced:
                events.extend(self._external([cell], others))
            return _eff(raw, EMPTY, 0, "burst"), events
        self._mem[cell] = value
        if replaced:
            events.extend(self._external([cell], others))
        if self._state.get(cell) != "remembered":
            events.append({"kind": "remembered", "cell": cell, "tok": _tok(value)})
        self._state[cell] = "remembered"
        return _eff(raw, value[0], value[1], "burst"), events


def burst_result(reads, conf_min, agree=2, empty_conf_min=0.0):
    """Accepted (type, pip) of one cell's burst, or None.

    reads = one raw read per kept grab. AI-NOTE: the caller drops pixel-identical grabs, so each read counts as a
    separate grab (duplicate-free assumption); a group needs >= agree reads. Ties: highest single conf, larger
    group, earlier first read.
    """
    groups = {}
    for i, d in enumerate(reads):
        if _unreadable(d, conf_min, empty_conf_min):
            continue
        key = (d["type"], d["pip"]) if d["type"] != EMPTY else (EMPTY, 0)
        g = groups.setdefault(key, [i, 0, 0.0])
        g[1] += 1
        g[2] = max(g[2], d["conf"])
    ok = [(-g[2], -g[1], g[0], k) for k, g in groups.items() if g[1] >= agree]
    return min(ok)[3] if ok else None


def merge_verdict(raw_from, raw_to, before_from, before_to, conf_min, empty_conf_min=0.0):
    """'effect' | 'none' | 'undecided' on RAW reads (R7.1). An unreadable read never counts as unchanged."""
    confident = []
    for d, before in ((raw_from, before_from), (raw_to, before_to)):
        if _unreadable(d, conf_min, empty_conf_min):
            confident.append(None)
        else:
            val = (d["type"], d["pip"]) if d["type"] != EMPTY else (EMPTY, 0)
            confident.append(val != tuple(before))
    if any(x for x in confident if x is not None):
        return "effect"
    return "none" if all(x is False for x in confident) else "undecided"
