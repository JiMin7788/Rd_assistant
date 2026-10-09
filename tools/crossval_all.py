"""Thorough label audit: cross-validated TYPE and PIP predictions on every labelled
crop of the hi-res sessions, then crop-level review sheets of every disagreement.

Folds are whole sessions, so each crop is predicted by models that never saw that
game. Flags (one review tile per flagged crop, 160 px from the hi-res crop):
  * type: CV type prediction (kind level, gear colours merged) != label
  * pip : CV pip prediction != label (Doom compared on corner pattern only;
          its centre is audited by the centre net)
Writes data/crops_gear/review_full/{flags.npy, sheet_XXX.png}.

  python tools/crossval_all.py --epochs 6
"""
import argparse, collections, os, sys
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import train_gear_pip_cnn as P
import train_gear_type_cnn as TT
from rdom.perception.gear import TYPES, TYPE_CLASSES, kind

ap = argparse.ArgumentParser(); ap.add_argument("--epochs", type=int, default=6)
a = ap.parse_args()
torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", 14)))
P.PATTERN = True
D = P.D; OUT = os.path.join(D, "review_full"); os.makedirs(OUT, exist_ok=True)
HI = ["s3", "s4", "s5", "s6", "s7", "s8", "s9"]
FOLDS = [["s3", "s4"], ["s5"], ["s6", "s7"], ["s8"], ["s9"]]
LO = ["s1", "s2"]


def type_set(tag, cap):
    X, Y, _ = TT.load(tag, cap=cap)
    names = np.load(os.path.join(D, f"feats_{tag}.npz" if tag != "s1" else "feats.npz"))["names"]
    yf = os.path.join(D, "y_fixed.npy" if tag == "s1" else f"y_{tag}.npy")
    y = np.load(yf, allow_pickle=True)
    return X, Y


flags = []        # (tag, crop index, kind_label, kind_pred, pip_label, pip_pred, why)
for fold in FOLDS:
    tr = LO + [t for t in HI if t not in fold]
    print("== fold", fold, flush=True)
    # ---- type
    Xs, Ys = zip(*[type_set(t, 6000 if t in ("s4", "s5", "s8", "s9") else (4000 if t in LO else 100000)) for t in tr])
    tnet = TT.train(np.concatenate(Xs), np.concatenate(Ys), a.epochs)
    # ---- pip
    pdata = [P.load(t) for t in tr]
    pnet = P.train(np.concatenate([d[0] for d in pdata]), np.concatenate([d[1] for d in pdata]),
                   np.concatenate([d[2] for d in pdata]), a.epochs)
    for tag in fold:
        names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
        y = np.load(os.path.join(D, f"y_{tag}.npy"), allow_pickle=True)
        pip = np.load(os.path.join(D, f"pip_{tag}.npy"))
        idx = np.where((y != "") & (y != "junk"))[0]
        crops = np.stack([cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", names[i] + ".png")), cv2.COLOR_BGR2RGB)
                          for i in idx])
        tp = TT.predict(tnet, crops)
        tk = np.array([kind(TYPE_CLASSES[c]) for c in tp]); yk = np.array([kind(t) for t in y[idx]])
        dice = np.array([y[i] in TYPES and pip[i] > 0 for i in idx])
        pp = np.zeros(len(idx), int)
        if dice.any():
            Ti = np.array([TYPES.index(y[i]) for i in idx[dice]])
            pp[dice] = P.predict(pnet, crops[dice], Ti) + 1
        nt = npip = 0
        for j, i in enumerate(idx):
            why = []
            if tk[j] != yk[j]:
                why.append("type"); nt += 1
            if dice[j]:
                l, p = pip[i], pp[j]
                if y[i] == "Doom":
                    l, p = (1 if l <= 1 else l // 2 * 2), (1 if p <= 1 else p // 2 * 2)
                if l != p:
                    why.append("pip"); npip += 1
            if why:
                flags.append((tag, int(i), yk[j], tk[j], int(pip[i]), int(pp[j]), "+".join(why)))
        print(f"   {tag}: crops {len(idx)}  type-disagree {nt} ({nt/len(idx):.4f})  pip-disagree {npip} "
              f"({npip/max(1,dice.sum()):.4f})", flush=True)
    del tnet, pnet

np.save(os.path.join(OUT, "flags.npy"), np.array(flags, dtype=object), allow_pickle=True)
print("flagged crops", len(flags), collections.Counter(f[6] for f in flags), flush=True)
tiles = []
for k, (tag, i, yk, tk, pl, pp, why) in enumerate(flags):
    names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"] if k == 0 or flags[k-1][0] != tag else names
    im = cv2.resize(cv2.imread(os.path.join(D, "_hires", names[i] + ".png")), (160, 160), interpolation=cv2.INTER_CUBIC)
    txt = f"{k} {yk[:2]}{pl}>{tk[:2]}{pp}"
    cv2.rectangle(im, (0, 0), (160, 18), (0, 0, 0), -1); cv2.putText(im, txt, (2, 14), 0, 0.45, (0, 255, 255), 1)
    tiles.append(im)
if tiles:
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 10)
    rows = [np.hstack(tiles[i:i+10]) for i in range(0, len(tiles), 10)]
    for s in range(0, len(rows), 5):
        cv2.imwrite(os.path.join(OUT, f"sheet_{s//5:03d}.png"), np.vstack(rows[s:s+5]))
print("sheets", (len(tiles) // 10 + 4) // 5, flush=True)
