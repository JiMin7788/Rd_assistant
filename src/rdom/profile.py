"""Capture/bot profiles, rdF04: LDPlayer (gear bot, unused) and two Google Play Games windows
(gpg = gear bot, gpg2 = support bot since rdT15).

A profile names the window config, the bot and the Discord tag. UI tap targets default to the
shared constants in :mod:`rdom.input.inject` (measured on GPG); ``ui`` holds the per-profile
overrides, read through :func:`uv`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from rdom.input import inject

__all__ = ["Profile", "PROFILES", "get", "uv"]


@dataclass(frozen=True)
class Profile:
    name: str
    bot: str        # "gear" | "support"
    tag: str        # Discord message tag
    config: str     # recorder toml, relative to the repo root
    ui: "MappingProxyType[str, tuple[float, float]]" = field(
        default_factory=lambda: MappingProxyType({}))


# AI-NOTE: keys are the inject.py constant names; only targets that differ from the shared
# (GPG) value are listed. Checked offline by tools/check_ld_profile.py (docstring = the run).
_LD_UI = MappingProxyType({
    # The pre-GPG LDPlayer value, inject.COOP_UV of commit 3a70f61^ (the commit that
    # re-measured it to 0.745 for GPG). Evidence frame: none on current LD -- the rdF04 LD
    # fixtures have no lobby. OPEN (H4): in the old LD session lobby frames (e.g.
    # 2026-10-07_2214_15c8 at 0 s) the green 협동 button spans v 0.699-0.803, so 0.823 would
    # sit below it; verify on the live LD window before the gear bot uses this.
    "COOP_UV": (0.497, 0.823),
})

PROFILES = {
    "ld": Profile("ld", "gear", "[기어]", "config/recorder_ld.toml", _LD_UI),
    # AI-NOTE: rdT06: LD is unused; the duo runs on two Google Play Games windows, each found by its
    # own exact window title (see the two recorder tomls). rdT15: gpg2 (배속봇, CleanCardinal77) plays a
    # support deck again, so its bot is "support" (tag [서폿]); gpg stays the gear bot.
    "gpg": Profile("gpg", "gear", "[기어1]", "config/recorder.toml"),
    "gpg2": Profile("gpg2", "support", "[서폿]", "config/recorder_gpg2.toml"),
}


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(f"unknown profile {name!r}; known: {sorted(PROFILES)}") from None


def uv(profile: Profile, key: str) -> tuple[float, float]:
    """Tap target `key` for `profile`: its override, else the shared inject constant."""
    if key in profile.ui:
        return profile.ui[key]
    return getattr(inject, key)
