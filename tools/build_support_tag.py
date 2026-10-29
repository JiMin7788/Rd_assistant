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


def _parse_fix(f, sheets, crops):
    """Reason string when the split fixes.tsv line is unusable, else (key, value): key is a sheet
    name with value 'ok', or (sheet, idx) with value None (drop) or (type, pip)."""
    if len(f) < 2 or not f[0].startswith("sheet_"):
        return "not a sheet line"
    if ":" not in f[0]:
        if f[1] != "ok":
            return f"unknown sheet action {f[1]!r}"
        return (f[0], "ok") if f[0] in sheets else f"no such sheet {f[0]}"
    sheet, _, idx = f[0].partition(":")
    if not idx.isdigit() or (sheet, int(idx)) not in crops:
        return f"no such crop {f[0]}"
    key = (sheet, int(idx))
    if f[1] == "drop":
        return key, None
    if f[1] not in SUPPORT_CLASSES:
        return f"unknown type {f[1]!r}"
    if len(f) < 3 or not f[2].isdigit() or not 1 <= int(f[2]) <= 7:
        return f"pip must be an int 1..7, got {f[2] if len(f) > 2 else 'nothing'!r}"
    return key, (f[1], int(f[2]))


def _read_fixes(path, label, sheets, crops):
    """(ticked sheets, fixes, ignored count). A line that is malformed, has a type outside
    SUPPORT_CLASSES, a pip outside 1..7 or names a sheet / crop missing from the review dir's
    index (sheets, crops) prints one warning line and is not applied."""
    ticked, fixes, ignored = set(), {}, 0
    if not os.path.exists(path):
        return ticked, fixes, ignored
    for no, line in enumerate(open(path, encoding="utf-8"), 1):
        if not line.strip():
            continue
        got = _parse_fix(line.rstrip("\n").split("\t"), sheets, crops)
        if isinstance(got, str):
            print(f"fixes.tsv {label}:{no}: {got} -- ignored")
            ignored += 1
        elif got[1] == "ok":
            ticked.add(got[0])
        else:
            fixes[got[0]] = got[1]
    return ticked, fixes, ignored


def _index_rows(idx_path):
    return [line.rstrip("\n").split("\t") for line in open(idx_path, encoding="utf-8") if line.strip()]


def _review(d):
    """(name -> dict(shown=(type, pip), label=(type, pip) or None for a drop, chk), ignored fixes
    lines). A ticked entry wins over an unticked one."""
    got, ignored = {}, 0
    root = os.path.join(d, "review")
    for sub in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        idx_path = os.path.join(root, sub, "index.tsv")
        if not os.path.exists(idx_path):
            continue
        rows = _index_rows(idx_path)
        ticked, fixes, bad = _read_fixes(os.path.join(root, sub, "fixes.tsv"), sub,
                                         {r[0] for r in rows}, {(r[0], int(r[1])) for r in rows})
        ignored += bad
        for sheet, idx, name, typ, pip in rows:
            key, shown = (sheet, int(idx)), (typ, int(pip))
            fixed = key in fixes
            chk = sheet in ticked
            if name in got and got[name]["chk"] and not chk:
                continue
            got[name] = {"shown": shown, "fixed": fixed, "chk": chk,
                         "label": fixes[key] if fixed else shown}
    return got, ignored


def build(d, tag, games=None):
    meta = {r["name"]: r for r in _jsonl(os.path.join(d, "crops.jsonl"))}
    pre = {r["name"]: r for r in _jsonl(os.path.join(d, "prelabels.jsonl"))}
    rev, ignored = _review(d)
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
    print(f"fixes.tsv lines ignored: {ignored}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--games", default=None, help="comma list of game ids; default all")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    a = ap.parse_args(argv)
    build(a.dir, a.tag, set(a.games.split(",")) if a.games else None)


if __name__ == "__main__":
    main()
