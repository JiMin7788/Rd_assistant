"""Score a pre-label file against an eye-checked TSV.

  python tools/check_prelabel.py EVAL.tsv PRELABELS.jsonl

EVAL.tsv: one `<crop name>\\t<Type>` per line (the type a human saw). Prints, per eye-checked type,
precision (of the crops pre-labelled T, the share that really are T), recall, and the share of the
set the pre-label left as '?'. Offline tool, not used by src/rdom.
"""
import collections
import json
import sys


def read_eval(path):
    with open(path, encoding="utf-8") as f:
        return dict(line.rstrip("\n").split("\t")[:2] for line in f if line.strip())


def read_pre(path):
    with open(path, encoding="utf-8") as f:
        return {r["name"]: r["type"] for r in map(json.loads, filter(str.strip, f))}


def score(truth, pred):
    """({type: (precision, hits, predicted, recall, actual)}, unknown_share, missing names)."""
    missing = [n for n in truth if n not in pred]
    names = [n for n in truth if n in pred]
    hit, npred, nact = collections.Counter(), collections.Counter(), collections.Counter()
    for n in names:
        nact[truth[n]] += 1
        npred[pred[n]] += 1
        hit[truth[n]] += pred[n] == truth[n]
    res = {t: (hit[t] / npred[t] if npred[t] else float("nan"), hit[t], npred[t],
               hit[t] / nact[t], nact[t]) for t in nact}
    return res, (npred["?"] / len(names) if names else float("nan")), missing


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.exit(__doc__)
    res, unk, missing = score(read_eval(argv[0]), read_pre(argv[1]))
    for t, (p, h, n, r, a) in sorted(res.items()):
        print(f"{t}: precision {p:.3f} ({h}/{n}) recall {r:.3f} ({h}/{a})")
    total = sum(a for *_, a in res.values())
    print(f"?: share {unk:.3f} ({round(unk * total)}/{total}) of the eye-checked crops left unlabelled")
    if missing:
        print(f"missing from pre-labels: {len(missing)} crop(s), e.g. {missing[0]}")


if __name__ == "__main__":
    main()
