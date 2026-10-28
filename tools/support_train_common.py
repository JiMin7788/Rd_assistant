"""Shared helpers of the support trainers (train_support_*.py) and tools/support_gate.py.

Layout under --data-dir (default <repo>/data): crops_gear/ (gear tags), crops_support/ (support
tags from build_support_tag.py), support_*.pt models, support_train_manifest.json.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
MANIFEST = "support_train_manifest.json"
GEAR_TAGS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "bomb", "live")


def read_rgb(path):
    im = cv2.imread(path)
    return None if im is None else cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def split_list(s):
    return [x for x in (s or "").split(",") if x]


def gear_tag(gear_dir, tag, need_pip=False):
    """(names, y, pip or None) of a gear tag, or None when its files are missing. An explicit
    tag list is used (not a glob): data/crops_gear holds stray y_*.npy / pip_*.npy files
    without a feats_ twin (y_init, pip_bomb)."""
    if tag == "s1":
        files = ("feats.npz", "y_fixed.npy", "pip.npy")
    else:
        files = (f"feats_{tag}.npz", f"y_{tag}.npy", f"pip_{tag}.npy")
    if not all(os.path.exists(os.path.join(gear_dir, f)) for f in files[:3 if need_pip else 2]):
        return None
    names = np.load(os.path.join(gear_dir, files[0]))["names"]
    y = np.load(os.path.join(gear_dir, files[1]), allow_pickle=True)
    pip = np.load(os.path.join(gear_dir, files[2])) if need_pip else None
    return names, y, pip


def support_tags(sup_dir):
    """Tags in sup_dir with all of feats_/y_/pip_/grp_ present."""
    if not os.path.isdir(sup_dir):
        return []
    out = []
    for f in sorted(os.listdir(sup_dir)):
        if f.startswith("feats_") and f.endswith(".npz"):
            t = f[len("feats_"):-len(".npz")]
            if all(os.path.exists(os.path.join(sup_dir, f"{k}_{t}.npy")) for k in ("y", "pip", "grp")):
                out.append(t)
    return out


def load_support(sup_dir, tags=None, exclude=()):
    """Concatenated support tags minus the excluded games: dict of names, y, pip, grp arrays."""
    tags = tags if tags else support_tags(sup_dir)
    cols = {"names": [], "y": [], "pip": [], "grp": []}
    for t in tags:
        names = np.load(os.path.join(sup_dir, f"feats_{t}.npz"))["names"]
        y = np.load(os.path.join(sup_dir, f"y_{t}.npy"), allow_pickle=True)
        pip = np.load(os.path.join(sup_dir, f"pip_{t}.npy"))
        grp = np.load(os.path.join(sup_dir, f"grp_{t}.npy"))
        keep = ~np.isin(grp, list(exclude))
        for k, v in zip(cols, (names, y, pip, grp)):
            cols[k].append(v[keep])
    if not cols["names"]:
        return {k: np.array([]) for k in cols}
    return {k: np.concatenate(v) for k, v in cols.items()}


def _write_json(path, obj):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def read_manifest(data_dir):
    p = os.path.join(data_dir, MANIFEST)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def record_manifest(data_dir, model_file, games):
    """Merge {model file name: sorted game ids it trained on} into the manifest (other entries kept)."""
    m = read_manifest(data_dir)
    m[os.path.basename(model_file)] = sorted({str(g) for g in games})
    _write_json(os.path.join(data_dir, MANIFEST), m)


def save_state(net, path):
    """Atomic: the bot hot-reloads model files."""
    import torch
    torch.save(net.state_dict(), path + ".tmp")
    os.replace(path + ".tmp", path)
