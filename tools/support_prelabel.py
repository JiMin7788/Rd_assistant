"""Pre-label the collected support-deck crops (data/crops_support) for human review.

  python tools/support_prelabel.py [--dir data/crops_support] [--out FILE]

Writes <dir>/prelabels.jsonl (or FILE), one line per crop in crops.jsonl that has a _raw PNG:
{name, type, pip, src, ambiguous, star_cand}.

Type: the gear type model's label when it is Bubble/Adjust/Growth/empty/junk/Crystal/Joker with
confidence >= 0.90 (src "gear-model"); else the offline colour rule (src "colour"); else the nearest
eye-checked seed crops in assets/prelabel_seeds/<Type>/ by gear-CNN feature similarity (src "seed");
else "?". Colour-, seed-labelled and "?" crops are `ambiguous` and go to review sheets
(tools/support_review.py); none is trained on unreviewed (R4, docs/07 §1.1).
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


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "prelabel_seeds")
SEED_K = 5            # neighbours that vote
SEED_MIN_SIM = 0.95   # cosine of the best neighbour below which the crop stays "?"
SEED_MIN_VOTE = 0.7   # share of the (similarity-weighted) vote the winning type needs
SLIME_FRAC = 0.14     # green share of the crop centre above which it is a slime splat, not a die
_bank = {}


def _features(crops):
    """L2-normalised features of the gear type CNN, one row per crop: the global average of the third
    conv block (64 channels). AI-NOTE: the net is only a feature extractor here, its class head is not
    used. Measured on the H1 eval set this beat the last block and any flattened (position-bound) map:
    the dice are shifted and glossy, so a position-free texture/colour summary generalises best."""
    import torch
    x = np.stack([cv2.resize(c, (gear.PIP_IN, gear.PIP_IN)) for c in crops]).astype(np.float32) / 255.0
    with torch.no_grad():
        f = gear._typenet().f[:3](torch.from_numpy(x.transpose(0, 3, 1, 2))).mean((2, 3)).numpy()
    return f / np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-9)


def seed_bank(seed_dir=SEED_DIR):
    """(features, labels) of the eye-checked seed crops <seed_dir>/<Type>/*.png, or None when there
    are none. Cached per directory."""
    key = os.path.abspath(seed_dir)
    if key not in _bank:
        crops, labs = [], []
        for t in sorted(os.listdir(seed_dir)) if os.path.isdir(seed_dir) else []:
            for fn in sorted(os.listdir(os.path.join(seed_dir, t))):
                if fn.endswith(".png") and (rgb := _read_rgb(os.path.join(seed_dir, t, fn))) is not None:
                    crops.append(rgb); labs.append(t)
        _bank[key] = (_features(crops), labs) if crops else None
    return _bank[key]


def _slime(rgb):
    """True when green slime covers the middle of the crop. AI-NOTE: a battle-effect slime splat hides
    the die face, but the CNN reads it as Resonance (green); on the H1 eval set the green share of the
    centre is <= 0.12 for real Resonance dice and 0.15..0.43 for slime. Offline pre-label only."""
    h = rgb.shape[0]
    m = rgb[int(h * .2):int(h * .8), int(h * .2):int(h * .8)]
    hsv = cv2.cvtColor(np.ascontiguousarray(m), cv2.COLOR_RGB2HSV)
    return ((hsv[..., 0] >= 40) & (hsv[..., 0] <= 90) & (hsv[..., 1] > 100) & (hsv[..., 2] > 100)).mean() > SLIME_FRAC


def seed_labels(crops, bank=None):
    """Nearest-neighbour type per crop against the seed bank: a weighted vote of the SEED_K most similar
    seeds, None when the best one is too dissimilar or the vote is not clear (the crop stays "?")."""
    bank = bank or seed_bank()
    if bank is None or not crops:
        return [None] * len(crops)
    sf, sl = bank
    sims = _features(crops) @ sf.T
    out = []
    for crop, row in zip(crops, sims):
        top = np.argsort(-row)[:SEED_K]
        if row[top[0]] < SEED_MIN_SIM or _slime(crop):
            out.append(None); continue
        votes = collections.defaultdict(float)
        for j in top:
            votes[sl[j]] += max(float(row[j]), 0.0)
        best = max(votes, key=votes.get)
        out.append(best if votes[best] / sum(votes.values()) >= SEED_MIN_VOTE else None)
    return out


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
        rest = [i for i, t in enumerate(types) if t == "?"]      # neither gear model nor colour rule
        for i, sl in zip(rest, seed_labels([crops[i] for i in rest])):
            if sl is not None:
                types[i], srcs[i] = sl, "seed"
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
    ap.add_argument("--out", help="write here instead of <dir>/prelabels.jsonl (for evaluation)")
    a = ap.parse_args(argv)
    out = prelabel(a.dir)
    with open(a.out or os.path.join(a.dir, "prelabels.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    print("prelabels", len(out), dict(collections.Counter(r["type"] for r in out)),
          "ambiguous", sum(r["ambiguous"] for r in out), "star_cand", sum(r["star_cand"] for r in out))


if __name__ == "__main__":
    main()
