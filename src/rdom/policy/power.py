"""Power-up order for the support deck. Pure functions, no I/O (the player does the tapping).

Order: Growth up to power_growth_first; then Alignment:Resonance by power_ratio; once
power_growth_late_after Alignment/Resonance purchases are made, Growth up to power_growth_late.
Taps without enough SP do nothing, so the order is recomputed from card levels at every
panel visit, never from the tap history alone. PowerTracker keeps the levels per game.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

CARDS = ("Growth", "Alignment", "Resonance")
INITIAL = 1          # every card starts a game at Lv.1
STRIKES_TO_MAX = 2


@dataclass(frozen=True)
class PowerConfig:
    growth_first: int = 7
    ratio: tuple = (3, 1)            # Alignment : Resonance
    growth_late: int = 8
    growth_late_after: int = 8       # A/R purchases before Growth goes on to growth_late


def load_power_config(path):
    """Read the power_* keys of [decks.support]; a missing file, bad TOML, a missing table
    or a missing key gives the default for it."""
    import tomllib
    cfg = PowerConfig()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return cfg
    t = data.get("decks", {}).get("support")
    if not isinstance(t, dict):
        return cfg
    if "power_growth_first" in t:
        cfg = replace(cfg, growth_first=int(t["power_growth_first"]))
    if "power_ratio" in t:
        cfg = replace(cfg, ratio=(int(t["power_ratio"][0]), int(t["power_ratio"][1])))
    if "power_growth_late" in t:
        cfg = replace(cfg, growth_late=int(t["power_growth_late"]))
    if "power_growth_late_after" in t:
        cfg = replace(cfg, growth_late_after=int(t["power_growth_late_after"]))
    return cfg


def _lv(levels, card):
    v = levels.get(card)
    return INITIAL if v is None else v


def next_card(levels, available, cfg=None):
    """The card to buy next, or None. levels: {card: level or None}; available: usable cards."""
    cfg = cfg or PowerConfig()
    g, a, r = (_lv(levels, c) for c in CARDS)
    pa, pr = a - 1, r - 1
    can_g = "Growth" in available
    if can_g and g < cfg.growth_first:
        return "Growth"
    if can_g and g < cfg.growth_late and pa + pr >= cfg.growth_late_after:
        return "Growth"
    can_a, can_r = "Alignment" in available, "Resonance" in available
    if can_a and can_r:
        x, y = cfg.ratio
        return "Resonance" if pa * y >= x * (pr + 1) else "Alignment"
    if can_a:
        return "Alignment"
    if can_r:
        return "Resonance"
    # AI-NOTE: with Alignment and Resonance both unusable, Growth is bought on up to growth_late
    # (nothing else to spend SP on); at growth_late there is nothing left to buy.
    if can_g and g < cfg.growth_late:
        return "Growth"
    return None


def plan_visit(levels, available, cfg=None, n=6):
    """Up to n taps for one panel visit, simulating the level rise of each purchase."""
    cfg = cfg or PowerConfig()
    lv = {c: _lv(levels, c) for c in CARDS}
    seq = []
    for _ in range(n):
        c = next_card(lv, available, cfg)
        if c is None:
            break
        seq.append(c)
        lv[c] += 1
    return seq


class PowerTracker:
    """Card levels per game: a level read from the screen, else the last read (1 if never)
    plus the taps made since. Detects cards that are maxed (taps no longer raise them)."""

    def __init__(self):
        self._base = {c: INITIAL for c in CARDS}
        self._taps = {c: 0 for c in CARDS}
        self._prev_read = {c: None for c in CARDS}
        self._tapped_visit = set()
        self._strikes = {c: 0 for c in CARDS}
        self._maxed = set()
        self._record = None

    def start_visit(self, read):
        """read: {card: level or None} (None = not read). Returns (levels, src, lines):
        src 'read' when every card was read, else 'count'; lines = new maxed log lines."""
        read = {c: read.get(c) for c in CARDS}
        newly = self._update_maxed(read)
        for c in CARDS:
            if read[c] is not None:
                self._base[c], self._taps[c] = read[c], 0
        levels = {c: self._base[c] + self._taps[c] for c in CARDS}
        src = "read" if all(v is not None for v in read.values()) else "count"
        lines = [f"power card {c} maxed at Lv {levels[c]}" for c in newly]
        self._prev_read = read
        self._tapped_visit = set()
        self._record = {"levels": dict(levels), "src": src, "maxed": sorted(self._maxed)}
        return levels, src, lines

    def _update_maxed(self, read):
        # AI-NOTE: only cards tapped last visit and read both now and at the visit before are
        # comparable; if none of them rose the cause was missing SP, which proves nothing.
        seen = [c for c in self._tapped_visit
                if read[c] is not None and self._prev_read[c] is not None]
        rose = [c for c in seen if read[c] > self._prev_read[c]]
        if not rose:
            return []
        newly = []
        for c in seen:
            if c in rose:
                self._strikes[c] = 0
                continue
            self._strikes[c] += 1
            if self._strikes[c] >= STRIKES_TO_MAX and c not in self._maxed:
                self._maxed.add(c)
                newly.append(c)
        return newly

    def tapped(self, seq):
        for c in seq:
            self._taps[c] += 1
            self._tapped_visit.add(c)

    def available(self):
        return tuple(c for c in CARDS if c not in self._maxed)

    def record(self):
        if self._record is None:
            return None
        r = self._record
        return {"levels": dict(r["levels"]), "src": r["src"], "maxed": list(r["maxed"])}

    @staticmethod
    def line(seq, levels, src):
        taps = "".join(c[0] for c in seq)
        lv = " ".join(f"{c[0]}{'-' if levels.get(c) is None else levels[c]}" for c in CARDS)
        return f"power panel -> {taps}, close (Lv {lv}, {src})"
