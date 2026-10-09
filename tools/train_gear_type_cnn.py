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
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", default=None, help="tag left out entirely and scored per kind")
    ap.add_argument("--epochs", type=int, default=8)
    a = ap.parse_args(); torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    CAPS = {"s1": 4000, "s2": 4000, "s3": 100000, "s6": 100000, "s7": 100000,
            "s4": 6000, "s5": 6000, "s8": 6000, "s9": 6000, "bomb": 100000}   # bomb = synthetic
    data = {t: load(t, cap=c) for t, c in CAPS.items() if os.path.exists(os.path.join(D, f"y_{t}.npy")) or t == "s1"}
    kind = lambda i: "Gear" if TYPE_CLASSES[i].startswith("Gear") else TYPE_CLASSES[i]
    tr = [t for t in data if t != a.holdout]
    X = np.concatenate([data[t][0] for t in tr]); Y = np.concatenate([data[t][1] for t in tr])
    if a.holdout:
        Xe, Ye, _ = load(a.holdout, cap=100000)
        def log(net):
            pr = predict(net, Xe); ks = sorted({kind(i) for i in Ye})
            per = {k: f"{np.mean([kind(p) == k for p, q in zip(pr, Ye) if kind(q) == k]):.3f}" for k in ks}
            return f"| {a.holdout} kind {np.mean([kind(p) == kind(q) for p, q in zip(pr, Ye)]):.4f} {per}"
        train(X, Y, a.epochs, log)
    else:
        net = train(X, Y, a.epochs)
        _dst = os.path.join(D, "..", "gear_type_cnn.pt")
        torch.save(net.state_dict(), _dst + ".tmp"); os.replace(_dst + ".tmp", _dst)   # atomic: the bot hot-reloads
        print("saved", _dst)
