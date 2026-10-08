"""Evaluate an ensemble of dot-position pip models (+ shift TTA) on a held-out tag.

  python tools/eval_pip_ensemble.py s9 data/ens/held_s9_seed1.pt data/ens/held_s9_seed2.pt ...
"""
import collections, os, sys
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import train_gear_pip_cnn as T
from rdom.perception.gear import TYPES, PipNet, PIP_IN, decode_pattern

tag, paths = sys.argv[1], sys.argv[2:]
torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", 14)))
X, Ty, P, _ = T.load(tag, cap=10**9); names = T.NAMES[tag]
SHIFTS = [(0, 0), (2, 0), (-2, 0), (0, 2), (0, -2)]


def logits(net, X, dx, dy):
    out = []
    with torch.no_grad():
        for i in range(0, len(X), 512):
            xb = X[i:i+512]
            if dx or dy:
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                xb = np.stack([cv2.warpAffine(im, M, (72, 72), borderMode=cv2.BORDER_REFLECT) for im in xb])
            out.append(net(T.plain(xb), torch.zeros(len(xb), dtype=torch.long)).numpy())
    return np.concatenate(out)


def score(L, label):
    pr = decode_pattern(L) - 1
    by = collections.defaultdict(list)
    for i, nm in enumerate(names):
        _, t, c = nm.split("_"); by[c].append((float(t), i))
    win = collections.defaultdict(lambda: [0, 0])
    for c, seq in by.items():
        seq.sort(); idx = [i for _, i in seq]; ts = [t for t, _ in seq]
        for k, i in enumerate(idx):
            w = [idx[j] for j in range(max(0, k-2), min(len(idx), k+3))
                 if Ty[idx[j]] == Ty[i] and P[idx[j]] == P[i] and abs(ts[j]-ts[k]) <= 3]
            win[Ty[i]][0] += collections.Counter(pr[w]).most_common(1)[0][0] == P[i]; win[Ty[i]][1] += 1
    print(f"== {label}: all {(pr == P).mean():.4f}")
    for t in sorted(win):
        m = Ty == t
        print(f"   {TYPES[t]:9s} single {(pr[m] == P[m]).mean():.4f}  window5 {win[t][0]/win[t][1]:.4f}  n={m.sum()}")


nets = []
for p in paths:
    net = PipNet(); net.load_state_dict(torch.load(p)); net.eval(); nets.append(net)
per_net = [logits(n, X, 0, 0) for n in nets]
for k, L in enumerate(per_net):
    score(L, f"model {k}")
score(np.mean(per_net, 0), f"ensemble x{len(nets)}")
tta = np.mean([logits(n, X, dx, dy) for n in nets for dx, dy in SHIFTS], 0)
score(tta, f"ensemble x{len(nets)} + shift TTA")
