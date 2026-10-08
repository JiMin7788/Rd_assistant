"""M1 5-class classifier self-test on synthetic cells.

Validates that the classifier separates the 5 deck classes
(Predator/Light/Resonance/Bubble/Switch) given clean input, isolating the
classifier logic from the sim-to-real gap (which needs target-deck frames).

For each class we composite its board sprite onto a slot-like background with
random scale/offset/brightness/pip-dots, then classify restricted to the 5
deck families. Reports a confusion matrix.
"""
from __future__ import annotations
import os, numpy as np, cv2
from PIL import Image

TPL_DIR = r"C:\dev\rdom\assets\templates\dice"
DECK = ["Dice_Predator", "Dice_Light", "Dice_Resonance", "Dice_BUBBLE", "Dice_Switch"]
N = 64
rng = np.random.default_rng(0)

TN = 44  # template inner size (smaller than N -> allows translation search)

def hue_hist(rgb_u8, mask=None):
    """Normalized hue histogram of colored (non-white, non-dark) pixels -- the
    theme color is the strongest discriminator between the 5 classes."""
    hsv = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sel = (s > 60) & (v > 40)
    if mask is not None:
        sel &= mask
    if sel.sum() < 20:
        return np.ones(18, np.float32) / 18
    hh = cv2.calcHist([h], [0], sel.astype(np.uint8), [18], [0, 180]).flatten()
    return (hh / hh.sum()).astype(np.float32)

def prep_template(rgba: Image.Image):
    a = np.array(rgba); alpha = a[:, :, 3]
    ys, xs = np.where(alpha > 40)
    if len(xs):
        rgba = rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    w, h = rgba.size
    m = 0.15
    inner = rgba.crop((int(w * m), int(h * m), int(w * (1 - m)), int(h * (1 - m))))
    g = np.array(inner.convert("L").resize((TN, TN))).astype(np.uint8)
    e = cv2.Canny(g, 60, 160).astype(np.float32)
    rgb = np.array(rgba.convert("RGB"))
    hmask = alpha[ys.min():ys.max()+1, xs.min():xs.max()+1] > 40 if len(xs) else None
    return e, hue_hist(rgb, hmask)

def templates():
    return {fam: prep_template(Image.open(os.path.join(TPL_DIR, fam + "3.png")).convert("RGBA"))
            for fam in DECK}

def classify(edge_full, rgb_cell, tpls):
    """Edge shape (translation-tolerant) + theme-color histogram."""
    ch = hue_hist(rgb_cell)
    best, bs = None, -9
    for fam, (te, th) in tpls.items():
        shape = float(cv2.matchTemplate(edge_full, te, cv2.TM_CCOEFF_NORMED).max())
        color = float(cv2.compareHist(ch, th, cv2.HISTCMP_CORREL))
        s = 0.5 * shape + 0.5 * color
        if s > bs:
            bs, best = s, fam
    return best, bs

def synth_cell(fam, i):
    """Composite the sprite onto a noisy slot bg with random perturbation."""
    spr = Image.open(os.path.join(TPL_DIR, fam + "3.png")).convert("RGBA")
    a = np.array(spr); alpha = a[:, :, 3]
    ys, xs = np.where(alpha > 40)
    spr = spr.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    scale = rng.uniform(0.85, 1.0)
    s = int(N * scale)
    spr = spr.resize((s, s))
    # slot background: bluish-gray with noise + brightness jitter
    bg_val = rng.integers(70, 130)
    bg = Image.fromarray((np.clip(np.array([[bg_val, bg_val, bg_val + 20]]) +
                          rng.normal(0, 12, (N, N, 3)), 0, 255)).astype(np.uint8))
    # dice sit roughly centered in a cell; small jitter only
    cx = (N - s) // 2 + int(rng.integers(-3, 4))
    cy = (N - s) // 2 + int(rng.integers(-3, 4))
    bg.paste(spr, (max(0, cx), max(0, cy)), spr)
    # overlay a few pip dots (simulate pip overlay)
    d = np.array(bg)
    for _ in range(rng.integers(1, 5)):
        px, py = rng.integers(8, N - 8, 2)
        cv2.circle(d, (int(px), int(py)), 3, (120, 80, 200), -1)
    g = cv2.cvtColor(d, cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(g, 60, 160).astype(np.float32)
    return e, d  # edge map + rgb cell

def main():
    tpls = templates()
    labels = DECK
    conf = {a: {b: 0 for b in labels} for a in labels}
    trials = 40
    for fam in labels:
        for i in range(trials):
            e, rgb = synth_cell(fam, i)
            pred, _ = classify(e, rgb, tpls)
            conf[fam][pred] += 1
    print("confusion (row=true, col=pred), %d trials each:" % trials)
    hdr = "            " + " ".join(f"{b.replace('Dice_',''):>10}" for b in labels)
    print(hdr)
    correct = 0
    for a in labels:
        row = " ".join(f"{conf[a][b]:>10}" for b in labels)
        print(f"{a.replace('Dice_',''):>11} {row}")
        correct += conf[a][a]
    print("overall accuracy: %.1f%%" % (100 * correct / (trials * len(labels))))

if __name__ == "__main__":
    main()
