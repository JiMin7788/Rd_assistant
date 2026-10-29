"""Turn pre-labels + reviewed sheets into a support training tag.

  python tools/build_support_tag.py --tag sup1 [--games g1,g2] [--dir data/crops_support]

Writes <dir>/{feats_<tag>.npz (names), y_, pip_, grp_ (game id), eff_ (buffed or glare), chk_}.
Per review dir (review/*/) fixes.tsv holds 'sheet_NN:<idx>\\t<Type>\\t<pip>', 'sheet_NN:<idx>\\tdrop'
and 'sheet_NN\\tok'. chk is true only for crops on an 'ok' sheet, labelled as the sheet SHOWED them
(index.tsv, not the current prelabels.jsonl) unless a fix line changes them. Others keep the current
pre-label (or a fix) with chk false. "?" and dropped crops are left out.
"""
import argparse
import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.support import SUPPORT_CLASSES

DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "crops_support")


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _read_fixes(path):
    ticked, fixes = set(), {}
    if not os.path.exists(path):
        return ticked, fixes
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 2 or not f[0].startswith("sheet_"):
            continue
        if ":" not in f[0]:
            if f[1] == "ok":
                ticked.add(f[0])
            continue
        sheet, idx = f[0].split(":")
        if f[1] == "drop":
            fixes[(sheet, int(idx))] = None
        else:
            if f[1] not in SUPPORT_CLASSES or len(f) < 3:
                raise SystemExit(f"bad fix line in {path}: {line.strip()!r}")
            fixes[(sheet, int(idx))] = (f[1], int(f[2]))
    return ticked, fixes


def _review(d):
    """name -> dict(shown=(type, pip), label=(type, pip) or None for a drop, chk). A ticked
    entry wins over an unticked one."""
    got = {}
    root = os.path.join(d, "review")
    for sub in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        idx_path = os.path.join(root, sub, "index.tsv")
        if not os.path.exists(idx_path):
            continue
        ticked, fixes = _read_fixes(os.path.join(root, sub, "fixes.tsv"))
        for line in open(idx_path, encoding="utf-8"):
            if not line.strip():
                continue
            sheet, idx, name, typ, pip = line.rstrip("\n").split("\t")
            key, shown = (sheet, int(idx)), (typ, int(pip))
            fixed = key in fixes
            chk = sheet in ticked
            if name in got and got[name]["chk"] and not chk:
                continue
            got[name] = {"shown": shown, "fixed": fixed, "chk": chk,
                         "label": fixes[key] if fixed else shown}
    return got


def build(d, tag, games=None):
    meta = {r["name"]: r for r in _jsonl(os.path.join(d, "crops.jsonl"))}
    pre = {r["name"]: r for r in _jsonl(os.path.join(d, "prelabels.jsonl"))}
    rev = _review(d)
    names, ys, pips, grp, eff, chk = [], [], [], [], [], []
    checked, fixed = collections.Counter(), collections.Counter()
    for name, p in pre.items():
        m = meta.get(name)
        if m is None or not os.path.exists(os.path.join(d, "_raw", name + ".png")):
            continue
        if games is not None and m["game"] not in games:
            continue
        r = rev.get(name)
        if r is not None and r["chk"]:
            label, c = r["label"], True
            checked[r["shown"][0]] += 1
            if label != r["shown"]:                       # a drop is label None, always != shown
                fixed[r["shown"][0]] += 1
        elif r is not None and r["fixed"]:
            label, c = r["label"], False
        else:
            label, c = (p["type"], p["pip"]), False
        if label is None or label[0] == "?":
            continue
        names.append(name); ys.append(label[0]); pips.append(label[1]); grp.append(m["game"])
        eff.append(bool(m.get("buffed") or m.get("glare"))); chk.append(c)
    np.savez(os.path.join(d, f"feats_{tag}.npz"), names=np.array(names))
    np.save(os.path.join(d, f"y_{tag}.npy"), np.array(ys, dtype=object))
    np.save(os.path.join(d, f"pip_{tag}.npy"), np.array(pips, dtype=np.int64))
    np.save(os.path.join(d, f"grp_{tag}.npy"), np.array(grp, dtype=str))
    np.save(os.path.join(d, f"eff_{tag}.npy"), np.array(eff, dtype=bool))
    np.save(os.path.join(d, f"chk_{tag}.npy"), np.array(chk, dtype=bool))
    print(tag, len(names), dict(collections.Counter(ys)))
    for t in sorted(checked):
        print(f"fix rate {t} {fixed[t]}/{checked[t]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--games", default=None, help="comma list of game ids; default all")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    a = ap.parse_args(argv)
    build(a.dir, a.tag, set(a.games.split(",")) if a.games else None)


if __name__ == "__main__":
    main()
