"""Doom centre-pip classifier (is the centre dot visible?) on native-res centre crops.

The Doom countdown number sits where the centre pip is; the centre dot is drawn
over it in some countdown phases and not in others, and at the 72 px training
scale it drowns in the digit strokes (pip CNN: Doom 84%). This net looks at the
64x64 centre of the 128 px hi-res crop. Corners come from the pip ensemble.

  python tools/train_doom_centre.py            -> data/gear_doom_centre_e{1,2,3}.pt
"""
import os, sys
import numpy as np, cv2, torch
import torch.nn.functional as Fn
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.gear import PipNet

D = r"C:\dev\rdom\data\crops_gear"
torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", 14)))
X, Y = [], []
for tag in ("s3", "s4", "s5", "s6", "s7", "s8", "s9"):
    names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
    y = np.load(os.path.join(D, f"y_{tag}.npy"), allow_pickle=True); p = np.load(os.path.join(D, f"pip_{tag}.npy"))
    for i in np.where((y == "Doom") & (p > 0))[0]:
        im = cv2.cvtColor(cv2.imread(os.path.join(D, "_hires", names[i] + ".png")), cv2.COLOR_BGR2RGB)
        X.append(im[24:88, 32:96]); Y.append(p[i] % 2 == 1)
X = np.stack(X); Y = np.array(Y, np.float32); print("doom crops", len(X), "odd", Y.mean())


def aug(xb, rng):
    out = []
    for im in xb:
        im = im.astype(np.float32); M = np.float32([[1, 0, rng.uniform(-4, 4)], [0, 1, rng.uniform(-4, 4)]])
        out.append(np.clip(cv2.warpAffine(im, M, (64, 64), borderMode=cv2.BORDER_REFLECT) * rng.uniform(.7, 1.3)
                           + rng.uniform(-30, 30), 0, 255))
    return torch.from_numpy(np.stack(out).transpose(0, 3, 1, 2) / 255.)


w = np.where(Y > 0, 1 / Y.mean(), 1 / (1 - Y.mean())); w /= w.sum()
for seed in (1, 2, 3):
    torch.manual_seed(seed); rng = np.random.RandomState(seed)
    net = PipNet(n_out=1); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-3)
    for step in range(2500):
        b = rng.choice(len(X), 64, p=w)
        loss = Fn.binary_cross_entropy_with_logits(net(aug(X[b], rng), torch.zeros(64, dtype=torch.long))[:, 0],
                                                   torch.from_numpy(Y[b]))
        opt.zero_grad(); loss.backward(); opt.step()
    dst = os.path.join(D, "..", f"gear_doom_centre_e{seed}.pt")
    torch.save(net.state_dict(), dst + ".tmp"); os.replace(dst + ".tmp", dst); print("saved", dst, flush=True)
