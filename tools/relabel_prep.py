"""Re-predict all hires-session crops with the current models, rebuild stable runs on
the new predictions, and draw a random sample of UNLABELLED runs for review sheets.

  python tools/relabel_prep.py --tags s4,s5,s6,s7,s8 --n 1000
Outputs data/crops_gear/review/{runs.npy, sheet_XX.png}
"""
import argparse, collections, os, sys
import numpy as np, cv2, torch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.gear import predict_types, predict_pips, TYPES, kind

ap = argparse.ArgumentParser(); ap.add_argument("--tags", default="s4,s5,s6,s7,s8")
ap.add_argument("--n", type=int, default=1000); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="review")
a = ap.parse_args()
torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", 8)))
D = r"C:\dev\rdom\data\crops_gear"; OUT = os.path.join(D, a.out); os.makedirs(OUT, exist_ok=True)
pool = []
for tag in a.tags.split(","):
    names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
    yp = os.path.join(D, f"y_{tag}.npy"); pp = os.path.join(D, f"pip_{tag}.npy")
    y = np.load(yp, allow_pickle=True) if os.path.exists(yp) else np.array([""] * len(names), dtype=object)
    p = np.load(pp) if os.path.exists(pp) else np.zeros(len(names), int)
    cache = os.path.join(OUT, f"pred_{tag}.npz")
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True); T, P = z["T"], z["P"]
    else:
        T, P = [], []
        for s in range(0, len(names), 2048):
            crops = [cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", n + ".png")), cv2.COLOR_BGR2RGB) for n in names[s:s+2048]]
            t, _ = predict_types(crops); T += t
            dice = [i for i, x in enumerate(t) if x in TYPES]
            pr = np.zeros(len(t), int)
            if dice:
                pr[dice] = predict_pips([crops[i] for i in dice], [t[i] for i in dice])
            P += list(pr)
            print(tag, s + len(crops), "/", len(names), flush=True)
        T, P = np.array(T, dtype=object), np.array(P)
        np.savez(cache, T=T, P=P)
    # stable runs on the new predictions: same cell, same kind, consecutive, no long gap
    bycell = collections.defaultdict(list)
    for i, n in enumerate(names):
        _, t, c = n.split("_"); bycell[int(c)].append((float(t), i))
    for c, seq in bycell.items():
        seq.sort(); cur = None
        for t, i in seq:
            if T[i] in ("junk", "empty"):
                continue
            if cur and kind(T[i]) == kind(T[cur[2][-1]]) and P[i] == P[cur[2][-1]] and t - cur[1] <= 2.0:
                cur[2].append(i); cur[1] = t
            else:
                if cur and len(cur[2]) >= 3: pool.append((tag, cur[2]))
                cur = [c, t, [i]]
        if cur and len(cur[2]) >= 3: pool.append((tag, cur[2]))
    # drop runs that are already labelled
    # skip runs already reviewed (any type label, incl. Doom/drop-free type-only labels)
    pool = [(tg, idx) for tg, idx in pool if tg != tag or ((p[idx] == 0).all() and (y[idx] == "").all())]
    globals().setdefault("META", {})[tag] = (names, T, P)
print("unlabelled runs", len(pool), "covering", sum(len(i) for _, i in pool), "crops", flush=True)
rng = np.random.RandomState(a.seed)
pick = [pool[i] for i in rng.choice(len(pool), min(a.n, len(pool)), replace=False)]
np.save(os.path.join(OUT, "runs.npy"), np.array([(tg, idx) for tg, idx in pick], dtype=object), allow_pickle=True)
print("sampled", len(pick), "runs covering", sum(len(i) for _, i in pick), "crops", flush=True)


def clean(tag, idx):
    names = META[tag][0]; best = None
    for i in idx[::max(1, len(idx) // 10)]:
        im = cv2.imread(os.path.join(D, "_hires", names[i] + ".png")); hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
        sc = (((hsv[..., 0] > 125) & (hsv[..., 0] < 150) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)).mean()
              + ((hsv[..., 0] > 85) & (hsv[..., 0] < 105) & (hsv[..., 1] > 120)).mean()
              + ((hsv[..., 1] < 30) & (hsv[..., 2] > 235)).mean())
        if best is None or sc < best[0]: best = (sc, im)
    return best[1]


tiles = []
for k, (tag, idx) in enumerate(pick):
    names, T, P = META[tag]
    im = cv2.resize(clean(tag, idx), (140, 140), interpolation=cv2.INTER_CUBIC)
    lab = f"{k} {kind(T[idx[0]])[:2]}{P[idx[0]]}"
    cv2.rectangle(im, (0, 0), (84, 20), (0, 0, 0), -1); cv2.putText(im, lab, (2, 15), 0, 0.5, (0, 255, 255), 1)
    tiles.append(im)
tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 10)
rows = [np.hstack(tiles[i:i+10]) for i in range(0, len(tiles), 10)]
for s in range(0, len(rows), 5):
    cv2.imwrite(os.path.join(OUT, f"sheet_{s//5:02d}.png"), np.vstack(rows[s:s+5]))
print("sheets", (len(rows) + 4) // 5)
