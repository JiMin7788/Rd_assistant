"""Support-deck die-type CNN (10 SUPPORT_CLASSES) -> <data-dir>/support_type_cnn.pt.

Gear tags give Bubble/Adjust/Growth/Joker/empty/junk/Crystal/Bomb (other gear classes are dropped);
the reviewed support tags add everything incl. Resonance/Alignment.

  python tools/train_support_type_cnn.py [--exclude-games g1,g2] [--tags sup1] [--epochs 8]

--exclude-games keeps held-out games out of training (tools/support_gate.py refuses games listed in
support_train_manifest.json, where each trainer records the games it used).
"""
import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(__file__))
import support_train_common as C
from rdom.perception.support import SUPPORT_CLASSES, TYPE_FILE
import train_gear_type_cnn as tt

GEAR_CAPS = {"s1": 4000, "s2": 4000, "s3": 100000, "s6": 100000, "s7": 100000,
             "s4": 6000, "s5": 6000, "s8": 6000, "s9": 6000, "bomb": 100000, "live": 6000}   # as train_gear_type_cnn


def _images(d, names):
    return [C.read_rgb(os.path.join(d, "_raw", n + ".png")) for n in names]


def gear_data(gear_dir, seed=0):
    """Gear crops whose label is a support class, capped per class like the gear trainer."""
    rng = np.random.RandomState(seed); X, Y = [], []
    for tag, cap in GEAR_CAPS.items():
        g = C.gear_tag(gear_dir, tag)
        if g is None:
            continue
        names, y, _ = g
        sel = []
        for c in SUPPORT_CLASSES:
            ii = np.where(y == c)[0]
            sel += list(rng.choice(ii, min(cap, len(ii)), replace=False)) if len(ii) else []
        sel = sorted(sel)
        X += _images(gear_dir, names[sel]); Y += [SUPPORT_CLASSES.index(y[i]) for i in sel]
    return X, Y


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=C.DATA)
    ap.add_argument("--tags", default="", help="comma list of support tags; default all")
    ap.add_argument("--exclude-games", default="", help="comma list of game ids kept out of training")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    torch.set_num_threads(int(os.environ.get("TRAIN_THREADS", os.cpu_count() or 4)))
    sup_dir = os.path.join(a.data_dir, "crops_support")
    X, Y = gear_data(os.path.join(a.data_dir, "crops_gear"), a.seed)
    s = C.load_support(sup_dir, C.split_list(a.tags), C.split_list(a.exclude_games))
    keep = [i for i, y in enumerate(s["y"]) if y in SUPPORT_CLASSES]
    X += _images(sup_dir, s["names"][keep]); Y += [SUPPORT_CLASSES.index(s["y"][i]) for i in keep]
    if not X:
        raise SystemExit("no training crops")
    net = tt.train(np.stack(X), np.array(Y), a.epochs, seed=a.seed, n_out=len(SUPPORT_CLASSES))
    dst = os.path.join(a.data_dir, TYPE_FILE)
    C.save_state(net, dst)
    C.record_manifest(a.data_dir, dst, s["grp"][keep])
    print("saved", dst)


if __name__ == "__main__":
    main()
