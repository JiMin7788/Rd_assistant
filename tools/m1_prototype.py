"""M1 recognition prototype: crop the 15 board cells and classify each by
template-matching against extracted dice sprites. Validation only -- not the
production recognizer. Run: python tools/m1_prototype.py <frame.png> [out.png]
"""
from __future__ import annotations
import glob, os, re, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

# M0 grid (content-normalized). Frames are 720x1280 and cover content 1:1.
COLS = [0.284, 0.390, 0.499, 0.610, 0.717]
ROWS = [0.551, 0.621, 0.690]
TPL_DIR = r"C:\dev\rdom\assets\templates\dice"
N = 64  # working size

def load_templates(variant="3"):
    """One template per family, preferring the board (3D) variant."""
    tpls = {}
    by_fam = {}
    for p in glob.glob(os.path.join(TPL_DIR, "*.png")):
        nm = os.path.basename(p)[:-4]
        m = re.match(r"(?i)(dice_[a-z]+)([0-9])$", nm)
        if not m:
            continue
        fam, var = m.group(1), m.group(2)
        by_fam.setdefault(fam, {})[var] = p
    for fam, vars_ in by_fam.items():
        p = vars_.get(variant) or vars_[sorted(vars_)[-1]]
        tpls[fam] = prep(Image.open(p).convert("RGBA"))
    return tpls

def prep(rgba: Image.Image):
    """Crop to alpha bbox, grayscale, resize NxN, return (gray, edges)."""
    a = np.array(rgba)
    alpha = a[:, :, 3]
    ys, xs = np.where(alpha > 40)
    if len(xs):
        rgba = rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    g = np.array(rgba.convert("L").resize((N, N)))
    e = cv2.Canny(g, 60, 160)
    return g.astype(np.float32), e.astype(np.float32)

def cell_boxes(W, H):
    hw, hh = int(0.050 * W), int(0.034 * H)
    boxes = []
    for rv in ROWS:
        for cu in COLS:
            cx, cy = int(cu * W), int(rv * H)
            boxes.append((cx - hw, cy - hh, cx + hw, cy + hh))
    return boxes

def ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = (np.linalg.norm(a) * np.linalg.norm(b))
    return float((a * b).sum() / d) if d else 0.0

def classify(cell_rgb, tpls):
    g = np.array(Image.fromarray(cell_rgb).convert("L").resize((N, N))).astype(np.float32)
    e = cv2.Canny(g.astype(np.uint8), 60, 160).astype(np.float32)
    # empty-slot heuristic: very few edges
    edge_density = (e > 0).mean()
    best, best_s = "empty", -1
    for fam, (tg, te) in tpls.items():
        s = 0.6 * ncc(g, tg) + 0.4 * ncc(e, te)
        if s > best_s:
            best_s, best = s, fam
    if edge_density < 0.02:
        return "empty", 0.0, edge_density
    return best.replace("Dice_", "").replace("dice_", ""), best_s, edge_density

def main():
    frame = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "m1_result.png"
    tpls = load_templates()
    img = Image.open(frame).convert("RGB"); W, H = img.size
    arr = np.array(img)
    boxes = cell_boxes(W, H)
    results = []
    for i, (x0, y0, x1, y1) in enumerate(boxes, 1):
        crop = arr[y0:y1, x0:x1]
        lab, sc, ed = classify(crop, tpls)
        results.append((i, lab, sc, ed))
    # montage
    cell = 150
    sheet = Image.new("RGB", (cell * 5, cell * 3 + 30), (30, 30, 35))
    dr = ImageDraw.Draw(sheet)
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        crop = img.crop((x0, y0, x1, y1)).resize((cell - 8, cell - 44))
        r, c = i // 5, i % 5
        px, py = c * cell + 4, r * cell + 4
        sheet.paste(crop, (px, py))
        n, lab, sc, ed = results[i]
        dr.text((px + 2, py + cell - 40), f"#{n} {lab}", fill=(255, 255, 0))
        dr.text((px + 2, py + cell - 26), f"s={sc:.2f} e={ed:.2f}", fill=(180, 220, 255))
    sheet.save(out)
    print("frame", os.path.basename(frame))
    for n, lab, sc, ed in results:
        print(f"  #{n:2d}  {lab:14s}  score={sc:.3f}  edge={ed:.3f}")
    print("wrote", out)

if __name__ == "__main__":
    main()
