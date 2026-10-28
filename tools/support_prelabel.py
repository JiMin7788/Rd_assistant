"""Pre-label the collected support-deck crops (data/crops_support) for human review.

  python tools/support_prelabel.py [--dir data/crops_support]

Writes <dir>/prelabels.jsonl, one line per crop in crops.jsonl that has a _raw PNG:
{name, type, pip, src, ambiguous, star_cand}.

Type: the gear type model's label when it is Bubble/Adjust/Growth/empty/junk/Crystal/Joker with
confidence >= 0.90 (src "gear-model"); else the offline colour rule (src "colour"); else "?".
Both colour-labelled and "?" crops are `ambiguous` and go to review sheets (tools/support_review.py);
none is trained on unreviewed (R4, docs/07 §1.1).
"""
import argparse
import collections
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception import gear, support

DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "crops_support")
GEAR_KEEP = ("Bubble", "Adjust", "Growth", "empty", "junk", "Crystal", "Joker")
GEAR_CONF = 0.90
STAR_P = 0.3
BATCH = 256


def _colour_label(rgb):
    """Offline face-colour rule on the centre of a crop: green -> Resonance, black or yellow ->
    Alignment, anything else None. AI-NOTE: this rule is allowed only here, as a pre-label that a
    human reviews; it must never run in src/rdom (hue bands misread under battle effects)."""
    h, w = rgb.shape[:2]
    c = rgb[h // 4:3 * h // 4, w // 4:3 * w // 4]
    hsv = cv2.cvtColor(np.ascontiguousarray(c), cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    coloured = (sat > 100) & (val > 100)
    if ((hue >= 35) & (hue <= 85) & coloured).mean() > 0.5:
        return "Resonance"
    if (val < 60).mean() > 0.5:
        return "Alignment"
    if ((hue >= 15) & (hue < 35) & coloured).mean() > 0.5:
        return "Alignment"
    return None


def _read_rgb(path):
    im = cv2.imread(path)
    return None if im is None else cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def prelabel(d):
    """Build the pre-label rows for every crop of <d>/crops.jsonl with a _raw PNG."""
    meta = [r for r in _read_jsonl(os.path.join(d, "crops.jsonl"))
            if os.path.exists(os.path.join(d, "_raw", r["name"] + ".png"))]
    gear.set_deck("doom")                          # AI-NOTE: no Decay remap in predict_types
    rows = {}
    for s in range(0, len(meta), BATCH):
        chunk = meta[s:s + BATCH]
        crops = [_read_rgb(os.path.join(d, "_raw", r["name"] + ".png")) for r in chunk]
        labs, conf = gear.predict_types(crops)
        types, srcs = [], []
        for lab, cf, crop in zip(labs, conf, crops):
            if lab in GEAR_KEEP and cf >= GEAR_CONF:
                types.append(lab); srcs.append("gear-model")
            elif (cl := _colour_label(crop)) is not None:
                types.append(cl); srcs.append("colour")
            else:
                types.append("?"); srcs.append("colour")
        dice = [i for i, t in enumerate(types) if t not in support.NO_PIP]
        pips = [0] * len(chunk)
        if dice:
            for i, p in zip(dice, gear.predict_pips([crops[i] for i in dice], [types[i] for i in dice])):
                pips[i] = int(p)
        sp = None
        if dice:
            hires = [_read_rgb(os.path.join(d, "_hires", chunk[i]["name"] + ".png")) for i in dice]
            if all(h is not None for h in hires):
                sp = support.star_prob(hires)
        star_p = {i: float(sp[k]) for k, i in enumerate(dice)} if sp is not None else {}
        for i, r in enumerate(chunk):
            src = srcs[i] if types[i] != "?" else "none"
            rows[r["name"]] = {"name": r["name"], "type": types[i], "pip": pips[i], "src": src,
                               "ambiguous": srcs[i] != "gear-model", "star_cand": star_p.get(i, 0.0) > STAR_P}
    # a 6 that is no longer a 6 may have been a 7 (star) the pip net could not see
    seq = collections.defaultdict(list)
    for r in meta:
        seq[(r["game"], r["cell"])].append(r)
    for lst in seq.values():
        lst.sort(key=lambda r: r["t"])
        for prev, cur in zip(lst, lst[1:]):
            p, c = rows[prev["name"]], rows[cur["name"]]
            if c["type"] not in support.NO_PIP and p["pip"] == 6 and c["pip"] != 6:
                c["star_cand"] = True
    return [rows[r["name"]] for r in meta]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    a = ap.parse_args(argv)
    out = prelabel(a.dir)
    with open(os.path.join(a.dir, "prelabels.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    print("prelabels", len(out), dict(collections.Counter(r["type"] for r in out)),
          "ambiguous", sum(r["ambiguous"] for r in out), "star_cand", sum(r["star_cand"] for r in out))


if __name__ == "__main__":
    main()
