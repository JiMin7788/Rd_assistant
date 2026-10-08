"""Die-type CNN for the gear deck (same net as the pip CNN, 10 outputs: 8 die
looks + empty + junk). The colour+HOG RandomForest read fire-glow Bubbles as red
gears (2026-10-07 bot game); a CNN with colour/glow augmentation learns shape.

  python tools/train_gear_type_cnn.py --eval   train s1+s2+s3[first half], test s3[second half]
  python tools/train_gear_type_cnn.py          train on everything -> data/gear_type_cnn.pt
"""
import argparse, os, sys, time
import numpy as np, cv2, torch
import torch.nn.functional as Fn
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from rdom.perception.gear import TYPE_CLASSES, PipNet
from train_gear_pip_cnn import augment, plain

D = r"C:\dev\rdom\data\crops_gear"


def load(tag, cap=4000, seed=0):
    if tag == "s1":
        names = np.load(os.path.join(D, "feats.npz"))["names"]
        y = np.load(os.path.join(D, "y_fixed.npy"), allow_pickle=True)
    else:
        names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
        y = np.load(os.path.join(D, f"y_{tag}.npy"), allow_pickle=True)
    t = np.array([float(n.split("_")[-2]) for n in names])
    rng = np.random.RandomState(seed); sel = []
    for c in TYPE_CLASSES:                       # cap per class: s1 has 11k red gears
        ii = np.where(y == c)[0]
        sel += list(rng.choice(ii, min(cap, len(ii)), replace=False)) if len(ii) else []
    sel = np.array(sorted(sel))
    X = np.stack([cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", names[i] + ".png")), cv2.COLOR_BGR2RGB) for i in sel])
    return X, np.array([TYPE_CLASSES.index(y[i]) for i in sel]), t[sel]


def train(X, Y, epochs, log=None, seed=0):
    torch.manual_seed(seed); rng = np.random.RandomState(seed)
    net = PipNet(n_out=len(TYPE_CLASSES)); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-3)
    cnt = np.bincount(Y, minlength=len(TYPE_CLASSES)); w = 1.0 / np.maximum(cnt[Y], 1); w /= w.sum()
    steps = max(1, len(X) // 128)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 3e-3, total_steps=epochs * steps)
    for ep in range(epochs):
        net.train(); t0 = time.time(); tot = 0
        for _ in range(steps):
            b = rng.choice(len(X), 128, p=w)
            # type must NOT be hue-blind (colour is the main cue): augment without hue rotation
            xb = augment(X[b], rng, hue=False)
            loss = Fn.cross_entropy(net(xb, torch.zeros(len(b), dtype=torch.long)), torch.from_numpy(Y[b]),
                                    label_smoothing=0.05)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); tot += loss.item()
        print(f"epoch {ep+1}/{epochs} loss {tot/steps:.3f} {time.time()-t0:.0f}s " + (log(net) if log else ""), flush=True)
    return net


def predict(net, X):
    net.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(X), 512):
            xb = plain(X[i:i+512]); out.append(net(xb, torch.zeros(len(xb), dtype=torch.long)).argmax(1).numpy())
    return np.concatenate(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--eval", action="store_true"); ap.add_argument("--epochs", type=int, default=8)
    a = ap.parse_args(); torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    X1, Y1, _ = load("s1"); X2, Y2, _ = load("s2"); X3, Y3, T3 = load("s3", cap=100000)
    X6, Y6, _ = load("s6", cap=100000)                     # crystals + relabelled bubbles
    X7, Y7, _ = load("s7", cap=100000)                     # jokers + adjust/doom
    X6, Y6 = np.concatenate([X6, X7]), np.concatenate([Y6, Y7])
    for _t in ("s4", "s5", "s8", "s9"):                    # random-review labels 2026-10-08
        if os.path.exists(os.path.join(D, f"y_{_t}.npy")):
            _x, _y, _ = load(_t, cap=6000); X6, Y6 = np.concatenate([X6, _x]), np.concatenate([Y6, _y])
    kind = lambda i: "Gear" if TYPE_CLASSES[i].startswith("Gear") else TYPE_CLASSES[i]
    if a.eval:
        h = np.median(T3); tr, te = T3 < h, T3 >= h
        def log(net):
            pr = predict(net, X3[te])
            k = np.mean([kind(p) == kind(q) for p, q in zip(pr, Y3[te])])
            bub = Y3[te] == TYPE_CLASSES.index("Bubble")
            return f"| s3-2nd kind {k:.3f} bubble {np.mean([kind(p)=='Bubble' for p in pr[bub]]):.3f}"
        train(np.concatenate([X1, X2, X3[tr], X6]), np.concatenate([Y1, Y2, Y3[tr], Y6]), a.epochs, log)
    else:
        net = train(np.concatenate([X1, X2, X3, X6]), np.concatenate([Y1, Y2, Y3, Y6]), a.epochs)
        _dst = os.path.join(r"C:\dev\rdom\data", "gear_type_cnn.pt")
        torch.save(net.state_dict(), _dst + ".tmp"); os.replace(_dst + ".tmp", _dst)   # atomic: the bot hot-reloads
