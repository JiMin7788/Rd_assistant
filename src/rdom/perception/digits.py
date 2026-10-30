"""Exact digit reading for the room code and the base HP (game UI font).

Tesseract misread room codes (14324 -> "14352") and HP (150 -> "15"/"190"), and a
wrong room code is useless, so this reader is built to be exact or say nothing:
  1. binarise the white digits, split them into connected components
  2. match each glyph against per-digit templates (built from verified screens,
     tools/build_digit_templates.py) by normalised correlation
  3. refuse (None) when any glyph is ambiguous (low score or small margin to the
     runner-up), when the glyph count is wrong, or the value is implausible.
Callers additionally require the same value on consecutive frames.
"""
from __future__ import annotations
import os
import numpy as np
import cv2

GW, GH = 20, 28                                    # normalised glyph size
_TPL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "templates")
_cache = {}


NORM_H = 120                                       # crops are scaled UP to this height


def normalise(gray):
    """Scale a crop up to NORM_H tall: shrinking made neighbouring digits touch."""
    return cv2.resize(gray, (int(gray.shape[1] * NORM_H / gray.shape[0]), NORM_H), interpolation=cv2.INTER_CUBIC)


def _split(mask, k):
    """Split a merged blob of k glyphs at the k-1 weakest columns (projection minima)."""
    w = mask.shape[1]; proj = mask.sum(0).astype(np.float32); cuts = []
    for j in range(1, k):
        c = int(round(j * w / k)); lo, hi = max(1, c - w // (3 * k)), min(w - 1, c + w // (3 * k))
        cuts.append(lo + int(np.argmin(proj[lo:hi])))
    edges = [0] + cuts + [w]
    return [mask[:, edges[i]:edges[i + 1]] for i in range(k)]


def hp_mask(bgr):
    """HP digits are near-white on a dark navy box inside a light-blue bevel: keep
    bright AND unsaturated pixels, and only inside the dark box (the bevel is blue,
    but its highlight passes a plain grey threshold)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # navy only (H 110+, strongly saturated): the grey-teal orb (H~104, S~110) is
    # dark too and used to stretch the "box" over itself
    dark = ((hsv[..., 0] >= 110) & (hsv[..., 1] > 150) & (hsv[..., 2] < 110)).astype(np.uint8)
    ys, xs = np.where(dark > 0)
    if len(xs) < 0.05 * dark.size:
        return None                                # no number box visible (popup / occluded)
    y0, y1, x0, x1 = np.percentile(ys, 2), np.percentile(ys, 98), np.percentile(xs, 2), np.percentile(xs, 98)
    m = ((hsv[..., 2] > 165) & (hsv[..., 1] < 90)).astype(np.uint8) * 255
    box = np.zeros_like(m); box[int(y0):int(y1)+1, int(x0):int(x1)+1] = 1
    m = m * box
    # the number is drawn CENTRED in its box: if the visible white is off-centre,
    # something (the orb, a popup edge) hides part of it -> refuse, never read "0"
    # out of a covered "150" (2026-10-09)
    ys2, xs2 = np.where(m > 0)
    if len(xs2) == 0:
        return None
    mid = (xs2.min() + xs2.max()) / 2; centre = bgr.shape[1] / 2
    if abs(mid - centre) > 0.10 * bgr.shape[1]:
        return None
    W = bgr.shape[1]
    if x0 > 0.15 * W or x1 < 0.85 * W:
        return None                                # box edge hidden (normally x0~0.10, x1~0.91)
    return m


def glyphs(gray, thr=170, min_h=0.30, max_h=0.95, merge_x=False, vis=1.0, geom=None):
    """White glyphs of a dark-background crop, left->right, each GHxGW float in 0..1.
    `gray` may also be a ready binary mask (0/255). Returns None if something that
    is not a glyph (blob, occluder) is in the way.
    merge_x: components whose x-ranges overlap by >= half of the narrower one are one glyph (a digit whose
    top was cut off by the crop falls apart into pieces); vis: visible fraction of a digit's height
    (the typical glyph width is 0.8 x the full digit height, so 0.8 / vis x the visible height).
    geom: optional list, filled with one (centre x, top y, bottom y) per returned glyph."""
    gray = normalise(gray); h = gray.shape[0]
    _, b = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    comps = []                                     # [x0, x1, y0, y1, [labels]]
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 0.004 * b.size:                     # specks
            continue
        if not merge_x and not (min_h * h <= hh <= max_h * h):
            return None                            # not a digit: occluder / glare
        comps.append([x, x + w, y, y + hh, [i]])
    if merge_x:
        comps.sort(); merged = []
        for c in comps:
            p = merged[-1] if merged else None
            if p and min(p[1], c[1]) - max(p[0], c[0]) >= 0.5 * min(p[1] - p[0], c[1] - c[0]):
                p[0], p[1], p[2], p[3] = min(p[0], c[0]), max(p[1], c[1]), min(p[2], c[2]), max(p[3], c[3]); p[4] += c[4]
            else:
                merged.append(c)
        comps = merged
        if any(not (min_h * h <= c[3] - c[2] <= max_h * h) for c in comps):
            return None
    if not comps:
        return None
    unit = np.median([c[3] - c[2] for c in comps]) * 0.80 / vis
    out = []
    for x0, x1, y0, y1, ids in comps:
        w = x1 - x0
        m = np.isin(lab[y0:y1, x0:x1], ids).astype(np.float32)
        k = max(1, int(round(w / unit))) if w > 1.15 * unit else 1
        if k > 4:
            return None
        for j, part in enumerate(_split(m, k) if k > 1 else [m]):
            ys, xs = np.where(part > 0)
            if len(xs) == 0:
                return None
            part = part[ys.min():ys.max()+1, xs.min():xs.max()+1]
            ph, pw = part.shape; side = max(ph, pw)
            part = cv2.copyMakeBorder(part, (side-ph)//2, side-ph-(side-ph)//2, (side-pw)//2, side-pw-(side-pw)//2,
                                      cv2.BORDER_CONSTANT, value=0)
            out.append((x0 + j * w / k, cv2.resize(part, (GW, GH), interpolation=cv2.INTER_AREA), (x0 + (j + 0.5) * w / k, y0, y1)))
    out.sort(key=lambda t: t[0])
    if geom is not None:                           # AI-NOTE: where each glyph sat (centre x, top y, bottom y, in normalised crop px) lets callers check the layout, which the square-padded glyph images no longer show
        geom[:] = [t[2] for t in out]
    return [t[1] for t in out]


def _templates(kind):
    if kind not in _cache:
        z = np.load(os.path.join(_TPL, f"digits_{kind}.npz"))
        _cache[kind] = z["T"]                      # (10, GH, GW), digit d at index d
    return _cache[kind]


def classify(g, T, min_score=0.80, min_margin=0.08):
    """(digit, score) or (None, score)."""
    v = g.ravel() - g.mean(); v /= (np.linalg.norm(v) + 1e-6)
    tv = T.reshape(10, -1); tv = tv - tv.mean(1, keepdims=True); tv /= (np.linalg.norm(tv, axis=1, keepdims=True) + 1e-6)
    s = tv @ v; o = np.argsort(-s)
    if s[o[0]] < min_score or s[o[0]] - s[o[1]] < min_margin:
        return None, float(s[o[0]])
    return int(o[0]), float(s[o[0]])


def _read_once(gray, kind, n_digits, thr, layout_ok=None, min_margin=0.08, **gkw):
    geom = []
    gs = glyphs(gray, thr, geom=geom, **gkw)
    if not gs or (n_digits and len(gs) != n_digits):
        return None
    if layout_ok and not layout_ok(geom, int(gray.shape[1] * NORM_H / gray.shape[0]), NORM_H):   # AI-NOTE: refused like an unsure glyph, so another threshold may still read cleanly
        return None
    T = _templates(kind); ds = []
    for g in gs:
        d, _ = classify(g, T, min_margin=min_margin)
        if d is None:
            return None
        ds.append(str(d))
    return "".join(ds)


def read_number(gray, kind, n_digits=None, thr=170, **gkw):
    """Read at a few thresholds (a high one thins the strokes so neighbouring digits
    stop touching). Every threshold that yields a confident read must agree,
    otherwise None -- disagreement means at least one read is wrong."""
    reads = {r for t in (thr + 40, thr + 20, thr) if t < 250 for r in [_read_once(gray, kind, n_digits, t, **gkw)] if r}
    return reads.pop() if len(reads) == 1 else None
