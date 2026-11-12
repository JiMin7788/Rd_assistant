"""Data-mode switches from config/data_mode.toml. Pure read, no other I/O.

sevens = true: both bots make as many pip-7 dice as possible and drop a 7 to a 6 with the supporter
(policy.gear.plan_next / policy.support.plan_support with sevens=True), plus extra crops of cells that
became pip 6/7 (collect.HiWatch). A missing file, bad TOML or anything but `sevens = true` -> off.
"""
from __future__ import annotations

import os

FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "data_mode.toml")


def sevens(path=None):
    """True only when the file has `sevens = true`; read once per game by gear_bot.play and PlayPlayer."""
    import tomllib
    try:
        with open(path or FILE, "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, ValueError):
        return False
    return cfg.get("sevens") is True
