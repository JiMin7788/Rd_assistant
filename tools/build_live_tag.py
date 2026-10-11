"""Turn the live-collected crops (src/rdom/perception/collect.py) into a training tag.

  python tools/build_live_tag.py [--tag live] [--types Decay]

Writes data/crops_gear/feats_<tag>.npz (names), y_<tag>.npy, pip_<tag>.npy in the
format of the s* tags, so the trainers take it with --tags ...,live (pip) and the
type trainer's CAPS. --types limits the tag to some die types (e.g. only Decay,
whose label comes from the colour rule, until the others are reviewed).
"""
import argparse, collections, json, os
import numpy as np

D = os.path.join(os.path.dirname(__file__), "..", "data", "crops_gear")
ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="live")
ap.add_argument("--types", default=None, help="comma list, e.g. Decay")
a = ap.parse_args()
keep = set(a.types.split(",")) if a.types else None

rows = [json.loads(l) for l in open(os.path.join(D, "live_labels.jsonl"), encoding="utf-8") if l.strip()]
rows = [r for r in rows if os.path.exists(os.path.join(D, "_raw", r["name"] + ".png"))
        and r["type"] not in ("junk",) and (keep is None or r["type"] in keep)]
names = np.array([r["name"] for r in rows])
np.savez(os.path.join(D, f"feats_{a.tag}.npz"), names=names)
np.save(os.path.join(D, f"y_{a.tag}.npy"), np.array([r["type"] for r in rows], dtype=object))
np.save(os.path.join(D, f"pip_{a.tag}.npy"), np.array([r["pip"] for r in rows], dtype=np.int64))
np.save(os.path.join(D, f"grp_{a.tag}.npy"), np.full(len(rows), -1))          # no review runs yet
print(a.tag, len(rows), dict(collections.Counter(r["type"] for r in rows)))
