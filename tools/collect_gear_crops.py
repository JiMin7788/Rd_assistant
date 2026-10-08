"""Cut the 15 own-board cells from a recorded session every STEP frames, save the
crops to data/crops_gear/_raw/<tag>_<t>_<cell>.png (72 px, training scale) and,
with --hires, sharp native-resolution crops to data/crops_gear/_hires/ for
labelling by eye. Pre-labels type+pip with the current gear models (batched).

  python tools/collect_gear_crops.py <session_dir> <tag> [--step 15] [--t0 S] [--t1 S] [--hires]
"""
import argparse, json, os, sys
import numpy as np
import cv2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.board import COLS, ROWS, HALF_W, HALF_H
from rdom.perception.features import cell_features
from rdom.perception.gear import cell_crops, predict_pips, _model, TYPES

ap = argparse.ArgumentParser()
ap.add_argument("session"); ap.add_argument("tag")
ap.add_argument("--step", type=int, default=15)
ap.add_argument("--t0", type=float, default=0); ap.add_argument("--t1", type=float, default=1e9)
ap.add_argument("--hires", action="store_true")
ap.add_argument("--ranges", default="", help='"a-b,c-d" seconds (overrides --t0/--t1)')
a = ap.parse_args()

D = r"C:\dev\rdom\data\crops_gear"
OUT, HI = os.path.join(D, "_raw"), os.path.join(D, "_hires")
os.makedirs(HI, exist_ok=True)


def hires_crops(rgb, size=128):
    h = rgb.shape[0]; W = round(h * 9 / 16); out = []
    for r in ROWS:
        for c in COLS:
            cx, cy, hw, hh = c * W, r * h, HALF_W * W, HALF_H * h
            out.append(cv2.resize(rgb[int(cy - hh):int(cy + hh), int(cx - hw):int(cx + hw)], (size, size),
                                  interpolation=cv2.INTER_AREA))
    return out


RANGES = [tuple(map(float, r.split("-"))) for r in a.ranges.split(",") if r] or [(a.t0, a.t1)]
in_range = lambda t: any(lo <= t <= hi for lo, hi in RANGES)
fr = [json.loads(l) for l in open(os.path.join(a.session, "frames.jsonl"))]
T0 = fr[0]["t"]
names, crops = [], []
for seg in sorted({f["seg"] for f in fr}):
    cap = cv2.VideoCapture(os.path.join(a.session, "video", f"seg_{seg:05d}.mp4"))
    for f in (f for f in fr if f["seg"] == seg):
        ok = cap.grab()
        if not ok:
            break
        rel = f["t"] - T0
        if f["i"] % a.step or not in_range(rel):
            continue
        ok, im = cap.retrieve()
        rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        hc = hires_crops(rgb) if a.hires else None
        for k, c in enumerate(cell_crops(rgb), 1):
            n = f"{a.tag}_{rel:07.1f}_{k:02d}"
            cv2.imwrite(os.path.join(OUT, n + ".png"), cv2.cvtColor(c, cv2.COLOR_RGB2BGR))
            if hc is not None:
                cv2.imwrite(os.path.join(HI, n + ".png"), cv2.cvtColor(hc[k - 1], cv2.COLOR_RGB2BGR))
            names.append(n); crops.append(c)
print(len(names), "crops; predicting", flush=True)
X = np.array([cell_features(c) for c in crops])
types = _model("type").predict(X)
dice = [i for i, t in enumerate(types) if t in TYPES]
pips = np.zeros(len(names), int)
for s in range(0, len(dice), 2048):
    idx = dice[s:s + 2048]
    pips[idx] = predict_pips([crops[i] for i in idx], [types[i] for i in idx])
np.savez(os.path.join(D, f"feats_{a.tag}.npz"), X=X, names=np.array(names),
         pred_type=types, pred_pip=pips)
print("done")
