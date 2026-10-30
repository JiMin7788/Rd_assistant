"""Confidence-floor report of the support type net on the human-checked holdout (sets READ_CONF_MIN).

  python tools/support_conf_report.py --holdout sup20261029_152652 --tags sup1 [--data-dir data]

For each threshold T prints how many checked crops keep conf >= T and how accurate the kept ones are,
then the largest T that still keeps >= 95% of the crops. Refuses a holdout game used in training.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import support_gate as G
import support_train_common as C
from rdom.perception import support

THRESHOLDS = (0.50, 0.60, 0.70, 0.80, 0.90, 0.95)
KEEP_MIN = 0.95


def report(y_true, y_pred, conf):
    """Pure. (lines, chosen T): one line per threshold, then the chosen-floor line."""
    ok = np.asarray(y_true, dtype=object) == np.asarray(y_pred, dtype=object)
    conf = np.asarray(conf, dtype=float)
    n = len(ok)
    lines, chosen = [], 0.50
    for t in THRESHOLDS:
        keep = conf >= t
        k = int(keep.sum())
        acc = float(ok[keep].sum()) / k if k else 0.0
        pct = 100.0 * k / n if n else 0.0
        lines.append(f"conf >= {t:.2f}: kept {k}/{n} ({pct:.1f}%), accuracy of kept {acc:.3f}, "
                     f"wrong kept {int((~ok[keep]).sum())}, wrong dropped {int((~ok[~keep]).sum())}")
        if n and k >= KEEP_MIN * n:
            chosen = t          # AI-NOTE: thresholds ascend, so the last one that still keeps >= 95% wins
    lines.append(f"chosen READ_CONF_MIN = {chosen:.2f} (largest with kept >= 95%)")
    return lines, chosen


EMPTY_THRESHOLDS = tuple(round(0.90 + 0.01 * i, 2) for i in range(10))
EMPTY_KEEP_MIN = 0.98


def report_empty(y_true, y_pred, conf):
    """Pure. (lines, chosen T or None): one line per T, then the choice line.

    true empty = label empty and read empty (b); other = label not empty but read empty with conf >= READ_CONF_MIN (d).
    """
    yt = np.asarray(y_true, dtype=object)
    yp = np.asarray(y_pred, dtype=object)
    conf = np.asarray(conf, dtype=float)
    true_empty = (yt == "empty") & (yp == "empty")
    other = (yt != "empty") & (yp == "empty") & (conf >= support.READ_CONF_MIN)
    b, d = int(true_empty.sum()), int(other.sum())
    lines, chosen = [], None
    for t in EMPTY_THRESHOLDS:
        a = int((true_empty & (conf >= t)).sum())
        c = int((other & (conf < t)).sum())
        lines.append(f"empty conf >= {t:.2f}: kept {a}/{b} true empty, rejected {c}/{d} other read as empty")
        # AI-NOTE: thresholds ascend, so the first T that rejects every other read and keeps >= 98% of true empties wins
        if chosen is None and c == d and b and a >= EMPTY_KEEP_MIN * b:
            chosen = t
    lines.append(f"chosen EMPTY_CONF_MIN = {chosen:.2f}" if chosen is not None
                 else "no EMPTY_CONF_MIN separates them -- unchanged")
    return lines, chosen


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", required=True, help="comma list of held-out game ids")
    ap.add_argument("--tags", default="", help="comma list of support tags; default all")
    ap.add_argument("--data-dir", default=support._DATA)
    ap.add_argument("--empty", action="store_true", help="report the stricter confidence cut for 'empty' reads")
    a = ap.parse_args(argv)
    holdout = C.split_list(a.holdout)
    used = {g for games in C.read_manifest(a.data_dir).values() for g in games}
    bad = [g for g in holdout if g in used]
    for g in bad:
        print(f"FAIL: holdout game {g} was used in training")
    if bad:
        return 1
    support._DATA = a.data_dir      # the type model is loaded from --data-dir
    support._models.clear()
    sup_dir = os.path.join(a.data_dir, "crops_support")
    missing = [t for t in C.split_list(a.tags) if not os.path.exists(os.path.join(sup_dir, f"feats_{t}.npz"))]
    if missing:
        print(f"FAIL: no feats file for tag {','.join(missing)} in {sup_dir}")
        return 1
    rows = G._holdout_rows(sup_dir, C.split_list(a.tags), holdout)
    if not rows:
        print("FAIL: no checked crops in the holdout games")
        return 1
    names, yt = [r[0] for r in rows], [r[1] for r in rows]
    crops = [C.read_rgb(os.path.join(sup_dir, "_raw", n + ".png")) for n in names]
    yp, conf = support.predict_types_support(crops)
    lines, _ = (report_empty if a.empty else report)(yt, yp, conf)
    for ln in lines:
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
