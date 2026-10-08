"""M1 real-frame validation: crop 15 cells and classify with the 5-class
color+edge recognizer validated in m1_selftest.py. Prints per-cell label and
draws a montage. Cells are all left of x=560 (safe from the overlapping notepad
in session 2026-09-16_0747_ab15).
"""
from __future__ import annotations
import os, sys, numpy as np, cv2
from PIL import Image, ImageDraw

TPL_DIR = r"C:\dev\rdom\assets\templates\dice"
DECK = ["Dice_Predator", "Dice_Light", "Dice_Resonance", "Dice_BUBBLE", "Dice_Switch"]
LAB = {"Dice_Predator": "Predator", "Dice_Light": "Light", "Dice_Resonance": "Reson",
       "Dice_BUBBLE": "Bubble", "Dice_Switch": "Switch"}
COLS = [0.284, 0.390, 0.499, 0.610, 0.717]
ROWS = [0.551, 0.621, 0.690]
N, TN = 64, 44

def hue_hist(rgb_u8, mask=None):
    hsv = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sel = (s > 60) & (v > 40)
    if mask is not None:
        sel &= mask
    if sel.sum() < 20:
        return np.ones(18, np.float32) / 18
    hh = cv2.calcHist([h], [0], sel.astype(np.uint8), [18], [0, 180]).flatten()
    return (hh / hh.sum()).astype(np.float32)

def load_templates():
    t = {}
    for fam in DECK:
        rgba = Image.open(os.path.join(TPL_DIR, fam + "3.png")).convert("RGBA")
        a = np.array(rgba); alpha = a[:, :, 3]
        ys, xs = np.where(alpha > 40)
        cr = rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        w, h = cr.size; m = 0.15
        inner = cr.crop((int(w*m), int(h*m), int(w*(1-m)), int(h*(1-m))))
        e = cv2.Canny(np.array(inner.convert("L").resize((TN, TN))).astype(np.uint8), 60, 160).astype(np.float32)
        hmask = alpha[ys.min():ys.max()+1, xs.min():xs.max()+1] > 40
        t[fam] = (e, hue_hist(np.array(cr.convert("RGB")), hmask))
    return t

def classify(cell_rgb, tpls):
    g = np.array(Image.fromarray(cell_rgb).convert("L").resize((N, N))).astype(np.uint8)
    edge = cv2.Canny(g, 60, 160).astype(np.float32)
    if (edge > 0).mean() < 0.015:
        return "empty", 0.0
    ch = hue_hist(cv2.resize(cell_rgb, (N, N)))
    best, bs = None, -9
    for fam, (te, th) in tpls.items():
        shape = float(cv2.matchTemplate(edge, te, cv2.TM_CCOEFF_NORMED).max())
        color = float(cv2.compareHist(ch, th, cv2.HISTCMP_CORREL))
        s = 0.5 * shape + 0.5 * color
        if s > bs:
            bs, best = s, fam
    return LAB[best], bs

def main():
    frame = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "m1_validate_out.png"
    tpls = load_templates()
    img = Image.open(frame).convert("RGB"); W, H = img.size
    arr = np.array(img)
    hw, hh = int(0.050 * W), int(0.034 * H)
    cell = 150
    sheet = Image.new("RGB", (cell*5, cell*3+20), (30, 30, 35))
    dr = ImageDraw.Draw(sheet)
    i = 0
    for rv in ROWS:
        for cu in COLS:
            cx, cy = int(cu*W), int(rv*H)
            box = (cx-hw, cy-hh, cx+hw, cy+hh)
            crop = arr[box[1]:box[3], box[0]:box[2]]
            lab, sc = classify(crop, tpls)
            r, c = i // 5, i % 5
            px, py = c*cell+4, r*cell+4
            sheet.paste(img.crop(box).resize((cell-8, cell-34)), (px, py))
            dr.text((px+2, py+cell-30), f"#{i+1} {lab}", fill=(255, 255, 0))
            dr.text((px+2, py+cell-16), f"{sc:.2f}", fill=(180, 220, 255))
            print(f"  #{i+1:2d}  {lab:9s}  {sc:.3f}")
            i += 1
    sheet.save(out)
    print("wrote", out)

if __name__ == "__main__":
    main()
