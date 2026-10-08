"""Cross-validated pip predictions to find label noise (confident-learning style).

Hi-res sessions are split into folds; for each fold a dot-position pip model is
trained on everything else and predicts every labelled crop of the fold. Runs
(same cell, consecutive, same label) where most predictions disagree with the
label are written to review_cv/ as sheets -- those are the labels to re-check.

  python tools/crossval_pip.py --epochs 4
"""
import argparse, collections, os, sys
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import train_gear_pip_cnn as T
from rdom.perception.gear import TYPES

ap = argparse.ArgumentParser(); ap.add_argument("--epochs", type=int, default=4)
ap.add_argument("--min_disagree", type=float, default=0.5)
a = ap.parse_args()
torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", 14)))
T.PATTERN = True
D = T.D; OUT = os.path.join(D, "review_cv"); os.makedirs(OUT, exist_ok=True)
FOLDS = [["s3", "s4", "s5"], ["s6", "s7"], ["s8", "s9"]]
ALL = ["s1", "s2"] + sum(FOLDS, [])

train_data = {t: T.load(t) for t in ALL}                    # capped, for training
rows = []                                                   # (tag, name, type, label, pred)
for fold in FOLDS:
    tr = [t for t in ALL if t not in fold]
    X = np.concatenate([train_data[t][0] for t in tr]); Ty = np.concatenate([train_data[t][1] for t in tr])
    P = np.concatenate([train_data[t][2] for t in tr])
    print("fold", fold, "train", len(X), flush=True)
    net = T.train(X, Ty, P, a.epochs)
    for t in fold:
        Xe, Te, Pe, _ = T.load(t, cap=10**9)
        pr = T.predict(net, Xe, Te)
        rows += [(t, n, TYPES[ty], int(l) + 1, int(p) + 1) for n, ty, l, p in zip(T.NAMES[t], Te, Pe, pr)]
        print(" ", t, "acc %.4f" % (pr == Pe).mean(), flush=True)
    del net

np.save(os.path.join(OUT, "cv_rows.npy"), np.array(rows, dtype=object), allow_pickle=True)
acc = collections.defaultdict(lambda: [0, 0])
for t, n, ty, l, p in rows:
    acc[ty][0] += l == p; acc[ty][1] += 1
print({k: f"{v[0]/v[1]:.4f} (n={v[1]})" for k, v in sorted(acc.items())}, flush=True)

# group into runs: same tag+cell, consecutive in time, same type+label
runs = []
by = collections.defaultdict(list)
for i, (t, n, ty, l, p) in enumerate(rows):
    _, tm, c = n.rsplit("_", 2); by[(t, c)].append((float(tm), i))
for key, seq in by.items():
    seq.sort(); cur = None
    for tm, i in seq:
        t, n, ty, l, p = rows[i]
        if cur and ty == cur[1] and l == cur[2] and tm - cur[3] <= 3.0:
            cur[0].append(i); cur[3] = tm
        else:
            if cur: runs.append(cur)
            cur = [[i], ty, l, tm]
    if cur: runs.append(cur)
flag = []
for idx, ty, l, _ in runs:
    preds = collections.Counter(rows[i][4] for i in idx)
    dis = 1 - preds[l] / len(idx)
    if dis >= a.min_disagree:
        flag.append((idx, ty, l, preds.most_common(1)[0][0], dis))
print("runs", len(runs), "flagged", len(flag), "covering", sum(len(f[0]) for f in flag), flush=True)
np.save(os.path.join(OUT, "flag.npy"), np.array(flag, dtype=object), allow_pickle=True)

tiles = []
for k, (idx, ty, l, p, dis) in enumerate(flag):
    i = idx[len(idx) // 2]
    im = cv2.resize(cv2.imread(os.path.join(D, "_hires", rows[i][1] + ".png")), (140, 140), interpolation=cv2.INTER_CUBIC)
    cv2.rectangle(im, (0, 0), (110, 20), (0, 0, 0), -1)
    cv2.putText(im, f"{k} {ty[:2]} L{l} m{p}", (2, 15), 0, 0.45, (0, 255, 255), 1)
    tiles.append(im)
if tiles:
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 10)
    rr = [np.hstack(tiles[i:i+10]) for i in range(0, len(tiles), 10)]
    for s in range(0, len(rr), 5):
        cv2.imwrite(os.path.join(OUT, f"sheet_{s//5:02d}.png"), np.vstack(rr[s:s+5]))
print("done", flush=True)
