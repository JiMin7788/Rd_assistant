"""Live training-data collection: while the bot plays it saves the 15 cell crops of
a stable board every EVERY seconds, with its own reading as a provisional label.

  data/crops_gear/_raw/live<YYYYMMDD>_<seconds>_<cell>.png   (same naming as the s* tags)
  data/crops_gear/live_labels.jsonl   {"name", "type", "pip", "conf"} per crop

tools/build_live_tag.py turns them into a training tag (feats_/y_/pip_ files).
Labels are the bot's reads -- review before trusting them for classes it misreads.
"""
from __future__ import annotations
import datetime, json, os, time
import cv2

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
RAW = os.path.join(_ROOT, "data", "crops_gear", "_raw")
LABELS = os.path.join(_ROOT, "data", "crops_gear", "live_labels.jsonl")
EVERY = 15.0
_last = [-1e9]


def maybe_save(frame_rgb, board, stable):
    """Save this board if it is stable and EVERY s passed. Never raises."""
    now = time.monotonic()
    if not stable or now - _last[0] < EVERY:
        return
    _last[0] = now
    try:
        from rdom.perception.gear import cell_crops
        os.makedirs(RAW, exist_ok=True)
        tag = "live" + datetime.date.today().strftime("%Y%m%d")
        t = time.time() % 100000
        rows = []
        for d, crop in zip(board, cell_crops(frame_rgb)):
            if d["type"] == "junk":
                continue
            name = f"{tag}_{t:.1f}_{d['cell']:02d}"
            cv2.imwrite(os.path.join(RAW, name + ".png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            rows.append({"name": name, "type": d.get("variant", d["type"]), "pip": d["pip"],
                         "conf": round(float(d.get("conf", 0)), 3)})
        with open(LABELS, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    except Exception as e:
        print("collect failed:", e, flush=True)


FAILS = os.path.join(_ROOT, "data", "merge_fail")


def save_fail(frame_rgb, a, b):
    """A merge the game refused: save both dice at native resolution side by side,
    named with what the bot read, e.g. 1824_120.5__GearTeal1-GearRed1.png."""
    try:
        import numpy as np
        from rdom.perception.gear import hires_cell
        os.makedirs(FAILS, exist_ok=True)
        im = np.hstack([hires_cell(frame_rgb, a["cell"], 160), hires_cell(frame_rgb, b["cell"], 160)])
        name = (f"{time.strftime('%m%d_%H%M%S')}__c{a['cell']}{a.get('variant', a['type'])}{a['pip']}"
                f"-c{b['cell']}{b.get('variant', b['type'])}{b['pip']}.png")
        cv2.imwrite(os.path.join(FAILS, name), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    except Exception as e:
        print("save_fail failed:", e, flush=True)


SUPPORT_DIR = os.path.join(_ROOT, "data", "crops_support")
COVERED_MSG = "frame not saved: game window covered"
_covered_logged = [-1e9]


def _covered_warn():
    """Print the covered notice at most once per 60 s (callers poll every 15-30 s)."""
    now = time.monotonic()
    if now - _covered_logged[0] >= 60.0:
        _covered_logged[0] = now
        print(COVERED_MSG, flush=True)


def save_support_cells(frame_rgb, game_id, t, unobscured, buffed=set(), glare=False):
    """Save the 15 own-board cells as 72 px (_raw) and 128 px (_hires) PNGs plus one
    crops.jsonl line each. Nothing is written when another window covers the game
    (R5). Never raises."""
    if not unobscured:
        _covered_warn()
        return
    try:
        from rdom.perception.gear import cell_crops, hires_cell
        raw, hires = os.path.join(SUPPORT_DIR, "_raw"), os.path.join(SUPPORT_DIR, "_hires")
        os.makedirs(raw, exist_ok=True)
        os.makedirs(hires, exist_ok=True)
        rows = []
        for cell, crop in enumerate(cell_crops(frame_rgb), 1):
            name = f"{game_id}_{t:.1f}_{cell:02d}"
            cv2.imwrite(os.path.join(raw, name + ".png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(hires, name + ".png"),
                        cv2.cvtColor(hires_cell(frame_rgb, cell, 128), cv2.COLOR_RGB2BGR))
            rows.append({"name": name, "game": game_id, "t": t, "cell": cell,
                         "buffed": cell in buffed, "glare": bool(glare)})
        with open(os.path.join(SUPPORT_DIR, "crops.jsonl"), "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    except Exception as e:
        print("save_support_cells failed:", e, flush=True)


def save_frame(frame_rgb, path, unobscured):
    """Write the full frame as PNG to `path` (parents created). Returns the path, or
    None when covered or on any error. Never raises."""
    if not unobscured:
        _covered_warn()
        return None
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not cv2.imwrite(str(path), cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)):
            return None
        return path
    except Exception as e:
        print("save_frame failed:", e, flush=True)
        return None


def save_burst(game_id, t, cells, grabs, unobscured, record):
    """Save every kept burst grab k of every cell as 72 px (_burst/_raw) and 128 px (_burst/_hires)
    PNGs plus one bursts.jsonl line (record + 'names' = the 72 px names). Returns the names; nothing is
    written and None is returned when another window covers the game (R5). Never raises."""
    if not unobscured:
        _covered_warn()
        return None
    try:
        from rdom.perception.gear import cell_crops, hires_cell
        base = os.path.join(SUPPORT_DIR, "_burst")
        raw, hires = os.path.join(base, "_raw"), os.path.join(base, "_hires")
        os.makedirs(raw, exist_ok=True)
        os.makedirs(hires, exist_ok=True)
        names = []
        for k, frame in enumerate(grabs):
            crops = cell_crops(frame)
            for cell in cells:
                name = f"{game_id}_{t:.1f}_{cell:02d}_{k}"
                cv2.imwrite(os.path.join(raw, name + ".png"),
                            cv2.cvtColor(crops[cell - 1], cv2.COLOR_RGB2BGR))
                cv2.imwrite(os.path.join(hires, name + ".png"),
                            cv2.cvtColor(hires_cell(frame, cell, 128), cv2.COLOR_RGB2BGR))
                names.append(name)
        with open(os.path.join(base, "bursts.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({**record, "names": names}) + "\n")
        return names
    except Exception as e:
        print("save_burst failed:", e, flush=True)
        return None
