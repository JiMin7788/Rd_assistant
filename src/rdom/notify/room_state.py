"""Room state shared between the game loop (writer) and the Discord bot (reader).

data/room.json   {"code": "12341" | null, "state": "waiting" | "playing" | "closed", "t": epoch}
data/discord_bot.alive   epoch of the Discord bot's last tick; while it is fresh the bot
                          hands out room codes (public card or reservation DM) and the
                          game loop must not post the code itself.
"""
from __future__ import annotations
import json, os, time

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
ROOM = os.path.join(DATA, "room.json")
ALIVE = os.path.join(DATA, "discord_bot.alive")


def write_room(code, state):
    try:
        tmp = ROOM + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"code": code, "state": state, "t": time.time()}, f)
        os.replace(tmp, ROOM)
    except Exception as e:
        print("room state write failed:", e, flush=True)


def read_room():
    try:
        with open(ROOM, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"code": None, "state": "closed", "t": 0}


def bot_alive(max_age=90):
    try:
        return time.time() - float(open(ALIVE).read()) < max_age
    except Exception:
        return False
