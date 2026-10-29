"""Hard Rule R4 gate of the support recognizers: accuracy on held-out games.

  python tools/support_gate.py --holdout g7,g8 [--tags sup1] [--data-dir data]

Evaluates only chk-true (human-reviewed) crops of the holdout games with the 'auto' pip source (the
support pip/star models when present), prints the two gate lines and writes <data-dir>/support_gate.json
(pass flags + sha256 of every support model file) that perception.support.gate_state() reads.
Refuses (exit 1, nothing written) a holdout game listed in support_train_manifest.json.
"""
import argparse
import datetime
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import support_train_common as C
from rdom.perception import support
from rdom.perception.support import NO_PIP, SUPPORT_CLASSES

MIN_ACC = 0.90
MIN_CLASS = 50      # crops of Resonance and of Alignment
MIN_STARS = 30      # pip-7 crops


def _ratio(num, den):
    return float(num) / den if den else 0.0


def metrics(y_true, y_pred, eff, pip_true, pip_pred):
    """Pure. All inputs are parallel sequences over the evaluated crops (human labels vs predictions).
    Resonance / Alignment are per-class recall (correct / human-labelled that class), not precision."""
    yt, yp = np.asarray(y_true, dtype=object), np.asarray(y_pred, dtype=object)
    eff = np.asarray(eff, dtype=bool)
    pt, pp = np.asarray(pip_true, dtype=int), np.asarray(pip_pred, dtype=int)
    ok = yt == yp
    t = {"n": int(len(yt)), "overall": _ratio(ok.sum(), len(yt)), "effect": _ratio(ok[eff].sum(), eff.sum())}
    for c in ("Resonance", "Alignment"):
        m = yt == c
        t[c] = _ratio(ok[m].sum(), m.sum()); t["n_" + c] = int(m.sum())
    ra = np.isin(yt, ("Resonance", "Alignment")) & (pt > 0)
    hit = pt == pp
    dice = np.isin(yt, SUPPORT_CLASSES) & ~np.isin(yt, NO_PIP) & (pt > 0)
    true7, pred7 = dice & (pt == 7), dice & (pp == 7)
    p = {"n": int(ra.sum()), "res_align": _ratio(hit[ra].sum(), ra.sum()),
         "effect": _ratio(hit[ra & eff].sum(), (ra & eff).sum()),
         "star_recall": _ratio((true7 & pred7).sum(), true7.sum()),
         "star_precision": _ratio((true7 & pred7).sum(), pred7.sum()), "stars": int(true7.sum())}
    return {"type": t, "pip": p}


def verdict(m):
    """(type_pass, pip_pass, [type line, pip line]); the lines are printed as is."""
    t, p = m["type"], m["pip"]
    few_t = t["n_Resonance"] < MIN_CLASS or t["n_Alignment"] < MIN_CLASS
    type_ok = (not few_t) and all(t[k] >= MIN_ACC for k in ("overall", "effect", "Resonance", "Alignment"))
    few_p = p["stars"] < MIN_STARS
    pip_ok = (not few_p) and all(p[k] >= MIN_ACC for k in ("res_align", "effect", "star_recall", "star_precision"))
    lt = (f"type gate: {'PASS' if type_ok else 'FAIL'} (overall {t['overall']:.3f}, effect {t['effect']:.3f}, "
          f"Resonance {t['Resonance']:.3f}, Alignment {t['Alignment']:.3f}, n={t['n']})" + (" too few samples" if few_t else ""))
    lp = (f"pip gate: {'PASS' if pip_ok else 'FAIL'} (Res/Align {p['res_align']:.3f}, effect {p['effect']:.3f}, "
          f"star recall {p['star_recall']:.3f}, star precision {p['star_precision']:.3f}, n={p['n']}, stars={p['stars']})"
          + (" too few samples" if few_p else ""))
    return type_ok, pip_ok, [lt, lp]


def _holdout_rows(sup_dir, tags, holdout):
    """Checked crops of the holdout games: (name, human type, human pip, eff)."""
    rows = []
    for t in tags if tags else C.support_tags(sup_dir):
        def L(k):
            return np.load(os.path.join(sup_dir, f"{k}_{t}.npy"), allow_pickle=True)
        names = np.load(os.path.join(sup_dir, f"feats_{t}.npz"))["names"]
        keep = np.isin(L("grp"), holdout) & L("chk").astype(bool)     # unticked pre-labels never count
        rows += list(zip(names[keep], L("y")[keep], L("pip")[keep], L("eff")[keep]))
    return rows


def _predict(sup_dir, names, y_true, pip_true):
    """Predicted types for all crops; predicted pips (auto source) for crops of a human die type."""
    crops = [C.read_rgb(os.path.join(sup_dir, "_raw", n + ".png")) for n in names]
    y_pred, _ = support.predict_types_support(crops)
    pip_pred = np.zeros(len(crops), dtype=int)
    di = [i for i, (y, p) in enumerate(zip(y_true, pip_true)) if y not in NO_PIP and p > 0]
    if di:
        pips = support.predict_pips_support([crops[i] for i in di], "auto")
        sp = None
        if all(os.path.exists(os.path.join(support._DATA, f)) for f in support.STAR_FILES):
            sp = support.star_prob([C.read_rgb(os.path.join(sup_dir, "_hires", names[i] + ".png")) for i in di])
        for k, i in enumerate(di):
            pip_pred[i] = pips[k] if sp is None else (7 if sp[k] > 0.5 else min(pips[k], 6))   # as read_board_support
    return y_pred, pip_pred


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", required=True, help="comma list of held-out game ids")
    ap.add_argument("--tags", default="", help="comma list of support tags; default all")
    ap.add_argument("--data-dir", default=support._DATA)
    a = ap.parse_args(argv)
    holdout = C.split_list(a.holdout)
    used = {g for games in C.read_manifest(a.data_dir).values() for g in games}
    bad = [g for g in holdout if g in used]
    for g in bad:
        print(f"FAIL: holdout game {g} was used in training")
    if bad:
        return 1
    support._DATA = a.data_dir      # AI-NOTE: model files, gate file and sha256 all resolve through support._DATA
    support._models.clear()
    sup_dir = os.path.join(a.data_dir, "crops_support")
    rows = _holdout_rows(sup_dir, C.split_list(a.tags), holdout)
    if not rows:
        print("FAIL: no checked crops in the holdout games")
        return 1
    names, yt, pt, eff = (list(c) for c in zip(*rows))
    yp, pp = _predict(sup_dir, names, yt, pt)
    m = metrics(yt, yp, eff, pt, pp)
    type_ok, pip_ok, lines = verdict(m)
    for ln in lines:
        print(ln)
    out = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "holdout": holdout,
           "type": {**m["type"], "pass": type_ok}, "pip": {**m["pip"], "pass": pip_ok},
           "models": {f: support._sha256(os.path.join(a.data_dir, f)) for f in support.model_files()}}
    gate_path = os.path.join(a.data_dir, support.GATE_FILE)
    C._write_json(gate_path, out)
    print(f"written {gate_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
