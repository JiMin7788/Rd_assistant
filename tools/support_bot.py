"""Support-deck bot core: deck routing, R6-guarded saver, R4 mode choice, R14 round record.

Small building blocks only; the per-tick players and main() come in later tasks. Importing this
module has no side effects (no grabber, injector, loop or file I/O).
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception import collect, support

ROUTE_FRAMES = 20
ROUTE_GAP = 0.5
ROUTE_NEED = 2                 # consecutive deck-bar hits


def route_deck(g, detect=None, force=None, sleep=time.sleep):
    """'support' or 'gear' for the battle on screen (R1). deck.toml `force` wins without looking."""
    detect = detect or support.detect_support_deck
    force = force or support.force_deck
    if force() == "support":
        print("deck route: support (forced by deck.toml)", flush=True)
        return "support"
    run = 0
    for i in range(ROUTE_FRAMES):
        if i:
            sleep(ROUTE_GAP)
        # AI-NOTE: consecutive hits required so one stray template match cannot flip the route.
        run = run + 1 if detect(g.grab()) else 0
        if run >= ROUTE_NEED:
            print("deck route: support (deck bar)", flush=True)
            return "support"
    print("deck route: gear", flush=True)
    return "gear"


class Saver:
    """All support-deck writes go through here; unobscured is re-read on every call (R6)."""

    def __init__(self, g):
        self.g = g

    def cells(self, frame, game_id, t, **kw):
        return collect.save_support_cells(frame, game_id, t, unobscured=self.g.unobscured(), **kw)

    def frame(self, frame, path):
        return collect.save_frame(frame, path, unobscured=self.g.unobscured())


def choose_mode(gates):
    """(mode, log line) from gate_state() (R4)."""
    if not gates["type"]:
        return "collect", "support deck: collect mode (type gate not passed)"
    if not gates["pip"]:
        return "trial", "support deck: trial mode (type gate PASS, pip gate FAIL)"
    return "play", "support deck: play mode (type gate PASS, pip gate PASS)"


def new_game_id(now=None):
    return (now or datetime.datetime.now()).strftime("sup%Y%m%d_%H%M%S")


def _iso(t):
    return t.isoformat() if isinstance(t, datetime.datetime) else t


def build_record(game_id, wall_start, wall_end, result, mode, gates, milestone_rec, power_rec, stats):
    """R14 round-record dict; milestone_rec from MilestoneTracker.record(), power_rec from
    PowerTracker.record() or None."""
    return {
        "game_id": game_id,
        "wall_start": _iso(wall_start),
        "wall_end": _iso(wall_end),
        "result": result,
        "mode": mode,
        "gates": dict(gates),
        "max_score": milestone_rec["max_score"],
        "scores_confirmed": milestone_rec["scores_confirmed"],
        "milestones": milestone_rec["milestones"],
        "crossings": milestone_rec["crossings"],
        "power": power_rec,
        "stats": stats,
    }


def append_round(path, record):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_battle(g, inj, minutes, route=route_deck, gear_play=None, support_play=None):
    """Route the battle, play it, hand over to the support player on 'wrong_deck'.
    Returns (result, player) so the caller can read player.stats."""
    if gear_play is None:
        import gear_bot
        gear_play = gear_bot.play
    # AI-NOTE: resolved at call time so this module works before play() exists (added later).
    if support_play is None:
        support_play = getattr(sys.modules[__name__], "play")
    player = support_play if route(g) == "support" else gear_play
    res = player(g, inj, minutes=minutes)
    if player is gear_play and res == "wrong_deck":
        print("deck route: support (gear bot hand-over)", flush=True)
        player = support_play
        res = player(g, inj, minutes=minutes)
    return res, player
