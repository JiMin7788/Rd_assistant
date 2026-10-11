"""Pip counter for the gear deck: small CNN (CPU), crop + die-type one-hot -> pip 1..7.

The ExtraTrees pip model memorised session 1 (40% on an unseen game), so this
learns to count with heavy augmentation instead: random shift/scale (dice sit at
slightly different spots per board row), colour/brightness jitter (bubble glow,
shadows) and random erasing (particles, splashes).

  python tools/train_gear_pip_cnn.py --eval s4   train on the other tags, report on s4
  python tools/train_gear_pip_cnn.py             train on all tags, save data/gear_pip_cnn.pt
"""
import argparse, os, sys, time
import numpy as np
import cv2
import torch
import torch.nn as nn
import torch.nn.functional as Fn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.gear import TYPES as _T, PipNet, PIP_IN, PIP_PATTERNS, decode_pattern
TYPES = _T + ("Decay",)                  # pip net is type-blind; Decay (부패) crops from live collection

D = r"C:\dev\rdom\data\crops_gear"


NAMES = {}


def load(tag, cap=8000, seed=0):
    if tag == "s1":
        names = np.load(os.path.join(D, "feats.npz"))["names"]
        y = np.load(os.path.join(D, "y_fixed.npy"), allow_pickle=True)
        pip = np.load(os.path.join(D, "pip.npy"))
        runs = np.load(os.path.join(D, "runs4.npy"), allow_pickle=True)
        grp = np.full(len(names), -1)
        for k, r in enumerate(runs): grp[r[2]] = k
    else:
        names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
        y = np.load(os.path.join(D, f"y_{tag}.npy"), allow_pickle=True)
        pip = np.load(os.path.join(D, f"pip_{tag}.npy"))
        grp = np.load(os.path.join(D, f"grp_{tag}.npy"))
    sel = np.where((pip > 0) & np.isin(y, TYPES))[0]
    # cap per (type, pip) so one session's flood of red gears can't dominate
    rng = np.random.RandomState(seed); keep = []
    for k in set(zip(y[sel], pip[sel])):
        ii = sel[(y[sel] == k[0]) & (pip[sel] == k[1])]
        keep += list(rng.choice(ii, min(cap, len(ii)), replace=False))
    sel = np.array(sorted(keep))
    X = np.stack([cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", names[i] + ".png")),
                               cv2.COLOR_BGR2RGB) for i in sel])
    T = np.array([TYPES.index(y[i]) for i in sel])
    NAMES[tag] = names[sel]
    return X, T, pip[sel] - 1, grp[sel]


PATTERN = False
_SPLASH = [(60.0, 120.0, 230.0), (120.0, 60.0, 200.0), (30.0, 30.0, 30.0), (240.0, 240.0, 240.0)]


def augment(xb, rng, hue=True):
    """xb: uint8 N,72,72,3 -> float tensor N,3,PIP_IN,PIP_IN"""
    out = np.empty((len(xb), PIP_IN, PIP_IN, 3), np.float32)
    for j, im in enumerate(xb):
        s = rng.uniform(0.88, 1.12); a = rng.uniform(-6, 6)
        M = cv2.getRotationMatrix2D((36, 36), a, s)
        M[:, 2] += rng.uniform(-6, 6, 2)
        im = cv2.warpAffine(im, M, (72, 72), borderMode=cv2.BORDER_REFLECT)
        im = im.astype(np.float32)
        im = im * rng.uniform(0.6, 1.3) + rng.uniform(-35, 35)          # brightness/contrast
        im = im * rng.uniform(0.85, 1.15, 3)                              # per-channel tint
        if hue and rng.rand() < 0.7:                                      # hue rotation: colour
            hsv = cv2.cvtColor(np.clip(im, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)  # must not
            hsv[..., 0] = (hsv[..., 0].astype(int) + rng.randint(180)) % 180              # predict pips
            im = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)
        if hue and rng.rand() < 0.2:
            im = np.repeat(im.mean(2, keepdims=True), 3, 2)
        if rng.rand() < 0.4:                                              # bubble-glow-like wash
            im = im * (1 - (w := rng.uniform(0.2, 0.55))) + 255 * w
        if rng.rand() < 0.5:                                              # particle/splash erase
            for _ in range(rng.randint(1, 4)):
                r = rng.randint(3, 9); cx, cy = rng.randint(0, 72, 2)
                col = _SPLASH[rng.randint(len(_SPLASH))]
                cv2.circle(im, (int(cx), int(cy)), int(r), col, -1)
        if rng.rand() < 0.35:                                             # specular glint/sparkle:
            gl = np.zeros((72, 72), np.float32)                           # a soft white spot that is
            for _ in range(rng.randint(1, 3)):                            # NOT a pip (grey gear read
                cx, cy = (36 + rng.uniform(-14, 14, 2)) if rng.rand() < 0.6 else rng.uniform(8, 64, 2)
                cv2.circle(gl, (int(cx), int(cy)), int(rng.randint(2, 6)), 1.0, -1)   # 2->3, 2026-10-09)
            gl = cv2.GaussianBlur(gl, (0, 0), rng.uniform(1.0, 2.5))[..., None]
            im = im * (1 - gl * 0.9) + 255 * gl * 0.9
        out[j] = cv2.resize(np.clip(im, 0, 255), (PIP_IN, PIP_IN))
    return torch.from_numpy(out.transpose(0, 3, 1, 2) / 255.0)


def plain(xb):
    out = np.stack([cv2.resize(im, (PIP_IN, PIP_IN)) for im in xb]).astype(np.float32) / 255.0
    return torch.from_numpy(out.transpose(0, 3, 1, 2))


def train(X, T, P, epochs, seed=0, log=None):
    torch.manual_seed(seed); rng = np.random.RandomState(seed)
    net = PipNet(); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-3)
    # balance classes: sample inversely to (type, pip) frequency
    key = T * 10 + P; uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    w = 1.0 / cnt[inv]; w /= w.sum()
    steps = max(1, len(X) // 128)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 3e-3, total_steps=epochs * steps)
    for ep in range(epochs):
        net.train(); t0 = time.time(); tot = 0
        for _ in range(steps):
            b = rng.choice(len(X), 128, p=w)
            xb = augment(X[b], rng); tb = torch.from_numpy(T[b]); pb = torch.from_numpy(P[b])
            out = net(xb, tb * 0)
            if PATTERN:      # per-dot-position BCE: positions generalise across die types
                tgt = torch.from_numpy(PIP_PATTERNS[pb.numpy()])
                loss = Fn.binary_cross_entropy_with_logits(out, tgt * 0.95 + 0.025)
            else:
                loss = Fn.cross_entropy(out, pb, label_smoothing=0.05)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); tot += loss.item()
        msg = f"epoch {ep+1}/{epochs} loss {tot/steps:.3f} {time.time()-t0:.0f}s"
        if log: msg += " " + log(net)
        print(msg, flush=True)
    return net


def predict(net, X, T):
    net.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(X), 512):
            o = net(plain(X[i:i+512]), torch.zeros(len(X[i:i+512]), dtype=torch.long)).numpy()
            out.append(decode_pattern(o) - 1 if PATTERN else o.argmax(1))
    return np.concatenate(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=None, help="held-out tag (trained on the others)")
    ap.add_argument("--tags", default="s1,s2,s3,s4,s6")
    ap.add_argument("--split", default=None, help="time-split held-out tag: train on its first half")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--pattern", action="store_true", help="dot-position head (gear_pip_pat.pt)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="save weights here (ensemble member)")
    a = ap.parse_args()
    PATTERN = a.pattern
    torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    data = {t: load(t) for t in a.tags.split(",")}
    tr = [t for t in data if t not in (a.eval, a.split)]
    X = np.concatenate([data[t][0] for t in tr]); T = np.concatenate([data[t][1] for t in tr])
    P = np.concatenate([data[t][2] for t in tr])
    if a.split:                                  # first half in, second half held out
        Xs, Ts, Ps, Gs = data[a.split]
        names = np.load(os.path.join(D, f"feats_{a.split}.npz"))["names"]
        y = np.load(os.path.join(D, f"y_{a.split}.npy"), allow_pickle=True); pp = np.load(os.path.join(D, f"pip_{a.split}.npy"))
        t = np.array([float(n.split("_")[-2]) for n in names])[(pp > 0) & np.isin(y, TYPES)]
        h = np.median(t); X = np.concatenate([X, Xs[t < h]]); T = np.concatenate([T, Ts[t < h]]); P = np.concatenate([P, Ps[t < h]])
        data["_held"] = (Xs[t >= h], Ts[t >= h], Ps[t >= h], None); a.eval = "_held"
    if a.eval:
        Xe, Te, Pe, _ = data[a.eval]
        def log(net):
            pr = predict(net, Xe, Te)
            per = {TYPES[t][:6]: f"{(pr[Te == t] == Pe[Te == t]).mean():.2f}" for t in np.unique(Te)}
            return f"| {a.eval} acc {(pr == Pe).mean():.3f} {per}"
        net = train(X, T, P, a.epochs, seed=a.seed, log=log)
        if a.out:
            torch.save(net.state_dict(), a.out)
        if a.eval in NAMES:     # dump held-out predictions for error review
            np.savez(os.path.join(D, f"heldout_pip_{a.eval}.npz"), names=NAMES[a.eval], T=Te, P=Pe,
                     pred=predict(net, Xe, Te))
    else:
        net = train(X, T, P, a.epochs, seed=a.seed)
        if a.out:
            torch.save(net.state_dict(), a.out); print("saved", a.out); sys.exit(0)
        _dst = os.path.join(r"C:\dev\rdom\data", "gear_pip_pat.pt" if PATTERN else "gear_pip_cnn.pt")
        torch.save(net.state_dict(), _dst + ".tmp"); os.replace(_dst + ".tmp", _dst)   # atomic: the bot hot-reloads
        print("saved", _dst)
