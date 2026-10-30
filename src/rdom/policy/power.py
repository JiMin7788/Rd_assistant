"""Power-up order for the support deck. Pure functions, no I/O (the player does the tapping).

Order: Growth up to power_growth_first; then Alignment:Resonance by power_ratio; once
power_growth_late_after Alignment/Resonance purchases are made, Growth up to power_growth_late.
SP above keep() = power_reserve_x * summon cost may be spent. Card levels are the game's confirmed
purchase count (PowerTracker); the digits on the screen only cross-check it.
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
    reserve_x: int = 3               # SP kept back = reserve_x * summon cost


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
    if "power_reserve_x" in t:
        cfg = replace(cfg, reserve_x=int(t["power_reserve_x"]))
    return cfg


def keep(cost, cfg=None):
    """SP to keep back for summons: reserve_x * summon cost."""
    return (cfg or PowerConfig()).reserve_x * cost


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
    """Card levels per game = 1 + the purchases the game confirmed (SP drop or level change).
    Screen digits only cross-check the count and never change it. A card whose purchase is
    refused twice in a row while SP was known and enough is maxed."""

    def __init__(self):
        self._bought = {c: 0 for c in CARDS}
        self._unconfirmed = 0
        self._strikes = {c: 0 for c in CARDS}
        self._maxed = []
        self._price = {c: None for c in CARDS}
        self._visits = 0
        self._chk = {"ok": 0, "field": 0, "mismatch": 0, "unread": 0}

    def levels(self):
        return {c: INITIAL + self._bought[c] for c in CARDS}

    def start_visit(self, read, found=None):
        """read: {card: level or None}; found: cards seen on the panel (None = all three).
        Compares the read digits with the count and returns the 'Lv check' log lines."""
        found = set(CARDS if found is None else found) & set(CARDS)
        rd = {c: read.get(c) if c in found else None for c in CARDS}
        got = [c for c in CARDS if rd[c] is not None]
        lv = self.levels()
        self._visits += 1
        if not got:
            self._chk["unread"] += 1
            return ["Lv check: not read"]
        shown = " ".join(f"{c[0]}{'-' if rd[c] is None else rd[c]}" for c in CARDS)
        diff = [c for c in got if rd[c] != lv[c]]
        if not diff:
            self._chk["ok"] += 1
            return [f"Lv check: read {shown} = count"]
        # AI-NOTE: the +1 is a per-game field effect on every card, so it is detected (all read
        # cards one above the count, at least two read) and never assumed; the count stays.
        if len(got) >= 2 and all(rd[c] == lv[c] + 1 for c in got):
            self._chk["field"] += 1
            return [f"Lv check: read {shown} = count +1 on every card (field effect)"]
        self._chk["mismatch"] += 1
        return [f"Lv check: {c} read {rd[c]}, count {lv[c]} (count kept)" for c in diff]

    def confirmed(self, card, price):
        """A purchase the game confirmed: counts, resets the card's strikes, remembers the price."""
        self._bought[card] += 1
        self._strikes[card] = 0
        self._price[card] = price

    def not_confirmed(self, card, affordable, sp_known):
        """A tap that was not confirmed. A strike only when SP was known and enough (a missing
        SP proves nothing). Returns the new maxed log lines."""
        self._unconfirmed += 1
        if not (affordable and sp_known):
            return []
        self._strikes[card] += 1
        if self._strikes[card] >= STRIKES_TO_MAX and card not in self._maxed:
            self._maxed.append(card)
            return [f"power card {card} maxed at Lv {self.levels()[card]}"]
        return []

    def last_price(self, card):
        return self._price[card]

    def available(self):
        return tuple(c for c in CARDS if c not in self._maxed)

    def record(self):
        if self._visits == 0:
            return None
        return {"levels": self.levels(), "src": "count", "maxed": sorted(self._maxed),
                "bought": sum(self._bought.values()), "unconfirmed": self._unconfirmed,
                "visits": self._visits, "lv_check": dict(self._chk), "price": dict(self._price)}

    @staticmethod
    def line(taps, levels, sp, keep, bought):
        lv = " ".join(f"{c[0]}{'-' if levels.get(c) is None else levels[c]}" for c in CARDS)
        sp = "?" if sp is None else sp
        keep = "?" if keep is None else keep
        return f"power panel -> {taps} ({bought} bought), close (Lv {lv}, SP {sp}, keep {keep})"
