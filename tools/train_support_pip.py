"""Support-deck pip counter (dot-pattern head) -> <data-dir>/support_pip_pat_e<seed>.pt.

Trains on gear + support tags, pip 1..6 only: pip 7 (star) belongs to train_support_star.py.
Run seeds 1..3 to get the ensemble perception/support.py expects.

  python tools/train_support_pip.py --seed 1 [--exclude-games g1,g2] [--epochs 12]
"""
import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(__file__))
import support_train_common as C
from rdom.perception.support import NO_PIP, SUPPORT_CLASSES
import train_gear_pip_cnn as tp

GEAR_PIP_TAGS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9")   # not bomb/live: no pips there
CAP = 8000                                                                  # per (type, pip), as the gear trainer


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=C.DATA)
    ap.add_argument("--tags", default="", help="comma list of support tags; default all")
    ap.add_argument("--exclude-games", default="")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None, help="default <data-dir>/support_pip_pat_e<seed>.pt")
    a = ap.parse_args(argv)
    torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    gear_dir, sup_dir = os.path.join(a.data_dir, "crops_gear"), os.path.join(a.data_dir, "crops_support")
    rng = np.random.RandomState(a.seed); X, P = [], []
    for tag in GEAR_PIP_TAGS:
        g = C.gear_tag(gear_dir, tag, need_pip=True)
        if g is None:
            continue
        names, y, pip = g
        sel = np.where((pip > 0) & (pip < 7) & np.isin(y, tp.TYPES))[0]
        keep = []
        for k in set(zip(y[sel], pip[sel])):          # cap per (type, pip): one session's red gears must not dominate
            ii = sel[(y[sel] == k[0]) & (pip[sel] == k[1])]
            keep += list(rng.choice(ii, min(CAP, len(ii)), replace=False))
        keep = sorted(keep)
        X += [C.read_rgb(os.path.join(gear_dir, "_raw", n + ".png")) for n in names[keep]]; P += list(pip[keep] - 1)
    s = C.load_support(sup_dir, C.split_list(a.tags), C.split_list(a.exclude_games))
    keep = [i for i, (y, p) in enumerate(zip(s["y"], s["pip"])) if y in SUPPORT_CLASSES and y not in NO_PIP and 0 < p < 7]
    X += [C.read_rgb(os.path.join(sup_dir, "_raw", n + ".png")) for n in s["names"][keep]]
    P += list(s["pip"][keep] - 1)
    if not X:
        raise SystemExit("no training crops")
    tp.PATTERN = True          # AI-NOTE: the gear trainer's PATTERN switch is a module global read inside tp.train
    P = np.array(P)
    net = tp.train(np.stack(X), np.zeros(len(X), dtype=np.int64), P, a.epochs, seed=a.seed)   # type-blind: T = 0
    dst = a.out or os.path.join(a.data_dir, f"support_pip_pat_e{a.seed}.pt")
    C.save_state(net, dst)
    C.record_manifest(a.data_dir, dst, s["grp"][keep])
    print("saved", dst)


if __name__ == "__main__":
    main()
