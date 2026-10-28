"""Star (pip 7) detector -> <data-dir>/support_star_e<seed>.pt: PipNet(n_out=1), BCE, positives =
crops labelled pip 7, negatives = other dice (pip 1..6). Input is the 128 px _hires crop of the
support tags (perception.support.star_prob resizes it to 64). Run seeds 1..3 for the ensemble.

  python tools/train_support_star.py --seed 1 [--exclude-games g1,g2] [--epochs 12]
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as Fn

sys.path.insert(0, os.path.dirname(__file__))
import support_train_common as C
from rdom.perception.support import NO_PIP, SUPPORT_CLASSES
from rdom.perception.gear import PipNet
import train_gear_pip_cnn as tp


def train(X, Y, epochs, seed):
    torch.manual_seed(seed); rng = np.random.RandomState(seed)
    net = PipNet(n_out=1); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-3)
    w = np.where(Y > 0, 0.5 / max(Y.sum(), 1), 0.5 / max((1 - Y).sum(), 1)); w /= w.sum()   # 50/50 star / not star
    steps = max(1, len(X) // 128)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 3e-3, total_steps=epochs * steps)
    for ep in range(epochs):
        net.train(); t0 = time.time(); tot = 0
        for _ in range(steps):
            b = rng.choice(len(X), 128, p=w)
            xb = tp.augment(X[b], rng, hue=False)       # the star is yellow: no hue rotation
            out = net(xb, torch.zeros(len(b), dtype=torch.long))[:, 0]
            loss = Fn.binary_cross_entropy_with_logits(out, torch.from_numpy(Y[b]))
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); tot += loss.item()
        print(f"epoch {ep+1}/{epochs} loss {tot/steps:.3f} {time.time()-t0:.0f}s", flush=True)
    return net


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=C.DATA)
    ap.add_argument("--tags", default="", help="comma list of support tags; default all")
    ap.add_argument("--exclude-games", default="")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None, help="default <data-dir>/support_star_e<seed>.pt")
    a = ap.parse_args(argv)
    torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    sup_dir = os.path.join(a.data_dir, "crops_support")
    s = C.load_support(sup_dir, C.split_list(a.tags), C.split_list(a.exclude_games))
    keep = [i for i, (y, p) in enumerate(zip(s["y"], s["pip"])) if y in SUPPORT_CLASSES and y not in NO_PIP and 0 < p <= 7]
    # AI-NOTE: tp.augment works on 72 px crops, so the 128 px hires crop is resized to 72 (it ends at 64 like star_prob's input)
    X = np.stack([cv2.resize(C.read_rgb(os.path.join(sup_dir, "_hires", n + ".png")), (72, 72), interpolation=cv2.INTER_AREA)
                  for n in s["names"][keep]]) if keep else np.zeros((0, 72, 72, 3), np.uint8)
    Y = (s["pip"][keep] == 7).astype(np.float32) if keep else np.zeros(0, np.float32)
    if Y.sum() == 0 or Y.sum() == len(Y):
        raise SystemExit("need both pip-7 and other-pip crops")
    net = train(X, Y, a.epochs, a.seed)
    dst = a.out or os.path.join(a.data_dir, f"support_star_e{a.seed}.pt")
    C.save_state(net, dst)
    C.record_manifest(a.data_dir, dst, s["grp"][keep])
    print("saved", dst)


if __name__ == "__main__":
    main()
