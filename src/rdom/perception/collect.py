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
