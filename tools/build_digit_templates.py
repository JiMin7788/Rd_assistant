"""Build per-digit templates from verified crops and score the reader on ALL crops.

Room codes: crops in data/digits/room/<...>_<code>.png; the code in the name came
from Tesseract and was checked by eye (FIX maps the misreads). HP: only crops
whose value was checked by eye (TRUST) feed the templates.

  python tools/build_digit_templates.py            # room + hp
  python tools/build_digit_templates.py score ...  # other kinds: data/digits/<kind>/<value>_<any>.png
"""
import collections, glob, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.digits import glyphs, classify, read_number, GW, GH, hp_mask

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "assets", "templates")
FIX = {"14352": "14324"}                                   # Tesseract misreads, checked by eye
TRUST_HP = {"10", "30", "50", "70", "90", "110", "130", "150", "190"}


def gray(path):
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def build(kind, items, thr=170, fallback=None, out=OUT):
    acc = collections.defaultdict(list)
    for g, label in items:
        gs = glyphs(g, thr)
        if gs and len(gs) == len(label):
            for d, gl in zip(label, gs):
                acc[int(d)].append(gl)
    missing = [d for d in range(10) if d not in acc]
    T = np.stack([np.mean(acc[d], 0) if d in acc else np.zeros((GH, GW), np.float32) for d in range(10)])
    if fallback is not None:                     # same game font (template corr 0.94-0.98)
        for d in missing:
            T[d] = fallback[d]
    np.savez(os.path.join(out, f"digits_{kind}.npz"), T=T)
    print(kind, "samples per digit", {d: len(acc[d]) for d in sorted(acc)}, "missing", missing)
    return missing


def build_kind(kind, src_dir, out=OUT, thr=170, fallback=None):
    """digits_<kind>.npz from <src_dir>/*.png; the value is the filename part before the first '_'
    (checked by eye). Digits without samples take `fallback` (the room templates from the CLI)."""
    items = []
    for p in sorted(glob.glob(os.path.join(src_dir, "*.png"))):
        value = os.path.basename(p).split("_", 1)[0]
        g = gray(p)
        if g is not None and value.isdigit():
            items.append((g, value))
    return build(kind, items, thr, fallback, out)


def main():
    room = []
    for p in glob.glob(os.path.join(ROOT, "data", "digits", "room", "*.png")):
        c = p.rsplit("_", 1)[1][:-4]; room.append((gray(p), FIX.get(c, c)))
    hp = []
    for p in glob.glob(os.path.join(ROOT, "data", "digits", "hp", "*.png")):
        c = p.rsplit("_", 1)[1][:-4]; m = hp_mask(cv2.imread(p))
        if m is not None: hp.append((m, c, p))
    build("room", room)
    R = np.load(os.path.join(OUT, "digits_room.npz"))["T"]
    build("hp", [(g, c) for g, c, _ in hp if c in TRUST_HP], thr=127, fallback=R)

    ok = bad = none = 0; errs = collections.Counter()
    for g, c in room:
        r = read_number(g, "room", 5)
        if r is None: none += 1
        elif r == c: ok += 1
        else: bad += 1; errs[(c, r)] += 1
    print(f"room: correct {ok}  WRONG {bad}  refused {none}  / {len(room)}", dict(errs))
    res = collections.Counter()
    for g, c, p in hp:
        r = read_number(g, "hp", thr=127)
        res[(c, r)] += 1
    print("hp (tesseract label, new read):", sorted(res.items(), key=lambda t: -t[1]))


if __name__ == "__main__":
    # AI-NOTE: room/hp run only from main() so tests can import build_kind without rewriting assets/templates
    # AI-NOTE: every argument used to be a kind name, so '--help' built assets/templates/digits_--help.npz
    import argparse
    ap = argparse.ArgumentParser(description="Build per-digit templates from verified crops (no kind: room + hp).")
    ap.add_argument("kinds", nargs="*", help="other kinds: data/digits/<kind>/<value>_<any>.png")
    kinds = ap.parse_args().kinds
    if kinds:
        R = np.load(os.path.join(OUT, "digits_room.npz"))["T"]
        for k in kinds:
            build_kind(k, os.path.join(ROOT, "data", "digits", k), fallback=R)
    else:
        main()
