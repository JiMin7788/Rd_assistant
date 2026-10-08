"""Feature vector for the learned die recogniser (M1b).

Combines COLOUR (fractions that already separate Predator/Resonance/Switch well)
with SHAPE (a HOG-like gradient-orientation histogram) so Light vs Bubble -- which
overlap on colour but differ in shape (white star cloud vs blue hexagon gem) -- can
be told apart. Used identically at training and inference time so the model sees
the same features it was trained on.
"""
from __future__ import annotations
import numpy as np
import cv2

CLASSES = ["Predator", "Light", "Resonance", "Bubble", "Switch", "empty", "Bomb"]


def _color_features(crop):
    h, w = crop.shape[:2]
    face = crop[int(h*0.16):int(h*0.62), int(w*0.22):int(w*0.78)]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sat = S > 55
    n = H.size
    def fr(m): return float((m & sat).sum() / n)
    tan = fr((H >= 8) & (H <= 32))
    green = fr((H >= 40) & (H <= 95))
    cyan = fr((H >= 95) & (H <= 122))
    purple = fr((H >= 123) & (H <= 150))
    pink = fr((H >= 148) & (H <= 172))
    white = float(((V > 190) & (S < 55)).sum() / n)
    brightwhite = float(((V > 210) & (S < 50)).sum() / n)
    darkblue = float(((H >= 95) & (H <= 145) & (S > 50) & (V < 170)).sum() / n)
    meanS = float(S.mean()) / 255.0
    meanV = float(V.mean()) / 255.0
    # border ring
    yy, xx = np.mgrid[0:h, 0:w]
    ring = ~((np.abs(yy - h/2) < h*0.33) & (np.abs(xx - w/2) < w*0.33))
    bh = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    bH, bS = bh[..., 0], bh[..., 1]
    bsat = (bS > 55) & ring
    bn = max(int(ring.sum()), 1)
    def bfr(m): return float((m & bsat).sum() / bn)
    btan = bfr((bH >= 8) & (bH <= 32))
    bgreen = bfr((bH >= 40) & (bH <= 95))
    bcyan = bfr((bH >= 95) & (bH <= 122))
    bpurple = bfr((bH >= 123) & (bH <= 150))
    bpink = bfr((bH >= 148) & (bH <= 172))
    darkfrac = float((V < 80).mean())
    # BOTTOM band of the die -- under the bubble effect the white glow overlay
    # washes the TOP but the lower part keeps its identity colour (user 2026-09-17),
    # so this band is the most glow-robust colour cue.
    bot = crop[int(h*0.55):int(h*0.88), int(w*0.22):int(w*0.78)]
    bhsv = cv2.cvtColor(bot, cv2.COLOR_RGB2HSV)
    bH, bS = bhsv[..., 0], bhsv[..., 1]
    bs = bS > 55; bnn = bH.size
    def bf(m): return float((m & bs).sum() / bnn)
    lo_tan = bf((bH >= 8) & (bH <= 32)); lo_grn = bf((bH >= 40) & (bH <= 95))
    lo_cyn = bf((bH >= 95) & (bH <= 122)); lo_pur = bf((bH >= 123) & (bH <= 150))
    lo_pnk = bf((bH >= 148) & (bH <= 172))
    return np.array([tan, green, cyan, purple, pink, white, brightwhite, darkblue,
                     meanS, meanV, btan, bgreen, bcyan, bpurple, bpink, darkfrac,
                     lo_tan, lo_grn, lo_cyn, lo_pur, lo_pnk], np.float32)


def _hog(crop, cells=4, bins=8):
    """HOG-like: grayscale, brightness-normalised, gradient-orientation histogram
    over a cells x cells grid. Captures the die's SHAPE robustly to overall glow."""
    g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, (48, 48)).astype(np.float32)
    g = (g - g.mean()) / (g.std() + 1e-6)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx*gx + gy*gy)
    ang = (np.arctan2(gy, gx) + np.pi) * (bins / (2*np.pi))   # 0..bins
    ang = np.minimum(ang.astype(int), bins - 1)
    H = 48 // cells
    out = []
    for r in range(cells):
        for c in range(cells):
            m = mag[r*H:(r+1)*H, c*H:(c+1)*H]
            a = ang[r*H:(r+1)*H, c*H:(c+1)*H]
            hist = np.bincount(a.ravel(), weights=m.ravel(), minlength=bins)
            out.append(hist)
    v = np.concatenate(out).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-6)


def cell_features(crop):
    """Full feature vector: colour (16) + HOG shape (4x4x8=128) = 144 dims."""
    return np.concatenate([_color_features(crop), _hog(crop)]).astype(np.float32)


CROP_ROOT = r"C:\dev\rdom\data\crops"


def strict_label(crop):
    """A CONFIDENT colour-rule label for auto-labelling training crops, or None when
    ambiguous (goes to _unlabeled for manual review). Deliberately strict -- only
    the unmistakable cases -- so auto-labels are trustworthy."""
    from rdom.perception.board import _dark_frac, _bright_frac
    if _dark_frac(crop) > 0.55:
        return "Bomb"
    h, w = crop.shape[:2]
    face = crop[int(h*0.16):int(h*0.62), int(w*0.22):int(w*0.78)]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    n = H.size; sat = S > 55
    fr = lambda m: float((m & sat).sum() / n)
    tan = fr((H >= 8) & (H <= 32)); green = fr((H >= 40) & (H <= 95))
    pink = fr((H >= 148) & (H <= 172))
    bw = float(((V > 210) & (S < 50)).sum() / n)
    darkblue = float(((H >= 95) & (H <= 145) & (S > 50) & (V < 170)).sum() / n)
    yy, xx = np.mgrid[0:h, 0:w]
    ring = ~((np.abs(yy - h/2) < h*0.33) & (np.abs(xx - w/2) < w*0.33))
    fh = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV); fH, fS = fh[..., 0], fh[..., 1]
    bsat = (fS > 55) & ring; bn = max(int(ring.sum()), 1)
    btan = float(((fH >= 8) & (fH <= 32) & bsat).sum() / bn)
    bgreen = float(((fH >= 40) & (fH <= 95) & bsat).sum() / bn)
    # true empty = flat tan tile: no bright die panel, and crucially NO blue/cyan
    # (a dark teal Bubble/Resonance die also has low bright/tan/green/pink, so the
    # old rule mislabelled ~2/3 of "empty" as dark dice -- check blue/cyan + edges).
    cyanb = float(((H >= 90) & (H <= 135) & (S > 45)).mean())
    g = cv2.cvtColor(face, cv2.COLOR_RGB2GRAY)
    edges = float((cv2.Canny(g, 50, 150) > 0).mean())
    if (_bright_frac(crop) < 0.12 and max(tan, green, pink) < 0.05
            and cyanb < 0.04 and edges < 0.08):
        return "empty"
    if tan >= 0.20 or btan >= 0.35:
        return "Predator"
    if green >= 0.35 or bgreen >= 0.42:
        return "Resonance"
    if pink >= 0.10:
        return "Switch"
    if bw >= 0.65 and darkblue < 0.03:
        return "Light"
    if bw < 0.12 or darkblue >= 0.22:
        return "Bubble"
    return None
