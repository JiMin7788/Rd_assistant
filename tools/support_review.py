"""Cut review sheets of 50 support crops (10 x 5 tiles of 128 px) for the human 'ok' review.

  python tools/support_review.py --ambiguous
  python tools/support_review.py --holdout <game_id>[,<game_id>] --n 1000 [--force]

--ambiguous: every ambiguous or star-candidate pre-label -> <dir>/review/amb/sheet_NN.png + index.tsv.
--holdout:   stratified seed-0 sample of the given games -> <dir>/review/hold_<ids>/ (ids joined by '+').
index.tsv has no header: sheet, idx, name, type, pip (tab-separated). Review = write fixes.tsv next
to it: 'sheet_NN:<idx>\\t<Type>\\t<pip>' or 'sheet_NN:<idx>\\tdrop' for a wrong tile, 'sheet_NN\\tok' once
the whole sheet was looked at. tools/build_support_tag.py turns that into tags.
"""
import argparse
import collections
import json
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "crops_support")
TILE = 128
COLS, ROWS = 10, 5
PER_SHEET = COLS * ROWS
CAPS = {"Resonance": 250, "Alignment": 250, "star": 150}      # holdout strata (seed 0)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def caption_text(idx, typ, pip):
    return f"#{idx} {typ} {pip}"


def caption_scale(text, limit=TILE - 2 - 4):
    """Largest font scale (<= 0.5) at which `text` is at most `limit` px wide. AI-NOTE: the full
    type name at 0.5 overflows a 128 px tile and clips the pip digit the reviewer confirms."""
    scale = 0.5
    while scale > 0.2 and cv2.getTextSize(text, FONT, scale, 1)[0][0] > limit:
        scale -= 0.02
    return scale


def _tile(d, name, idx, typ, pip):
    im = None
    for sub in ("_hires", "_raw"):
        im = cv2.imread(os.path.join(d, sub, name + ".png"))
        if im is not None:
            break
    if im is None:
        im = np.zeros((TILE, TILE, 3), np.uint8)
    im = cv2.resize(im, (TILE, TILE), interpolation=cv2.INTER_CUBIC)
    text = caption_text(idx, typ, pip)
    scale = caption_scale(text)
    (w, h), base = cv2.getTextSize(text, FONT, scale, 1)
    cv2.rectangle(im, (0, 0), (w + 4, h + base + 4), (0, 0, 0), -1)
    cv2.putText(im, text, (2, h + 2), FONT, scale, (0, 255, 255), 1)
    return im


def _fixes(path):
    """(ticked sheet names, all sheet numbers named in fixes.tsv)."""
    ticked, nums = set(), set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if not f[0].startswith("sheet_"):
                continue
            sheet = f[0].split(":")[0]
            nums.add(int(sheet[6:]))
            if len(f) == 2 and f[0] == sheet and f[1] == "ok":
                ticked.add(sheet)
    return ticked, nums


def _read_index(path):
    if not os.path.exists(path):
        return []
    return [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8") if l.strip()]


def _cut(d, out, items, start):
    """Write sheets for items (dicts with name/type/pip/star_cand) numbered from `start`;
    one pre-label type per sheet, star candidates on their own sheets. Returns index rows."""
    groups = collections.defaultdict(list)
    for it in items:
        groups[(bool(it["star_cand"]), it["type"])].append(it)
    rows, n = [], start
    for key in sorted(groups):
        g = sorted(groups[key], key=lambda it: it["name"])
        for s in range(0, len(g), PER_SHEET):
            chunk = g[s:s + PER_SHEET]
            tiles = [_tile(d, it["name"], i, it["type"], it["pip"]) for i, it in enumerate(chunk)]
            tiles += [np.zeros((TILE, TILE, 3), np.uint8)] * (PER_SHEET - len(tiles))
            img = np.vstack([np.hstack(tiles[r * COLS:(r + 1) * COLS]) for r in range(ROWS)])
            sheet = f"sheet_{n:02d}"
            cv2.imwrite(os.path.join(out, sheet + ".png"), img)
            rows += [[sheet, str(i), it["name"], it["type"], str(it["pip"])] for i, it in enumerate(chunk)]
            n += 1
    return rows


def _write_index(out, rows):
    with open(os.path.join(out, "index.tsv"), "w", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")


def _prelabels(d):
    with open(os.path.join(d, "prelabels.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def ambiguous(d):
    """Cut sheets for ambiguous / star-candidate crops not yet on a ticked sheet. Ticked sheets
    stay as they are; unticked ones are re-cut under NEW numbers (a number is never reused, so
    an old fixes.tsv line cannot land on a different crop)."""
    out = os.path.join(d, "review", "amb")
    os.makedirs(out, exist_ok=True)
    ticked, nums = _fixes(os.path.join(out, "fixes.tsv"))
    old = _read_index(os.path.join(out, "index.tsv"))
    keep = [r for r in old if r[0] in ticked]
    for r in old:
        if r[0] not in ticked:
            p = os.path.join(out, r[0] + ".png")
            if os.path.exists(p):
                os.remove(p)
    nums |= {int(r[0][6:]) for r in old}
    done = {r[2] for r in keep}
    items = [p for p in _prelabels(d) if (p["ambiguous"] or p["star_cand"]) and p["name"] not in done]
    rows = _cut(d, out, items, max(nums) + 1 if nums else 0)
    _write_index(out, keep + rows)
    return rows


def holdout(d, games, n, force=False):
    """Stratified seed-0 sample of the crops of `games`, cut into review/hold_<ids>/. Refuses to
    overwrite an existing review (its ticks belong to the old sheets) unless force; force moves
    the old fixes.tsv to fixes.tsv.old. Returns {"Resonance","Alignment","star","fill"} counts."""
    out = os.path.join(d, "review", "hold_" + "+".join(games))
    if not force and any(os.path.exists(os.path.join(out, f)) for f in ("index.tsv", "fixes.tsv")):
        raise SystemExit(f"{out} already has index.tsv/fixes.tsv; --force re-cuts and archives fixes.tsv")
    game_of = {}
    with open(os.path.join(d, "crops.jsonl"), encoding="utf-8") as f:
        for l in f:
            if l.strip():
                r = json.loads(l); game_of[r["name"]] = r["game"]
    pool = sorted((p for p in _prelabels(d) if game_of.get(p["name"]) in games), key=lambda p: p["name"])
    rng = np.random.RandomState(0)
    taken, picked, counts = set(), [], {}

    def take(label, cands, cap):
        cands = [p for p in cands if p["name"] not in taken]
        sel = [cands[i] for i in sorted(rng.choice(len(cands), min(cap, len(cands)), replace=False))] if cands else []
        taken.update(p["name"] for p in sel); picked.extend(sel); counts[label] = len(sel)

    take("Resonance", [p for p in pool if p["type"] == "Resonance"], CAPS["Resonance"])
    take("Alignment", [p for p in pool if p["type"] == "Alignment"], CAPS["Alignment"])
    take("star", [p for p in pool if p["star_cand"]], CAPS["star"])
    take("fill", pool, max(0, n - len(picked)))
    os.makedirs(out, exist_ok=True)
    for fn in os.listdir(out):
        if fn.startswith("sheet_") and fn.endswith(".png"):
            os.remove(os.path.join(out, fn))
    fx = os.path.join(out, "fixes.tsv")
    if os.path.exists(fx):
        shutil.move(fx, fx + ".old")
    _write_index(out, _cut(d, out, picked, 0))
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ambiguous", action="store_true")
    g.add_argument("--holdout", help="game_id[,game_id]")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    a = ap.parse_args(argv)
    if a.ambiguous:
        rows = ambiguous(a.dir)
        print("ambiguous: sheets", len({r[0] for r in rows}), "crops", len(rows))
        # AI-NOTE: QA S23 expects the written paths on stdout, not only the count; rows holds just the newly cut sheets.
        out = os.path.join(a.dir, "review", "amb")
        for sheet in sorted({r[0] for r in rows}):
            print(os.path.join(out, sheet + ".png"))
        print(os.path.join(out, "index.tsv"))
    else:
        print("holdout:", holdout(a.dir, a.holdout.split(","), a.n, a.force))


if __name__ == "__main__":
    main()
