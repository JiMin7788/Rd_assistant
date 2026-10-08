"""Measure per-cell colour signatures to build a robust Light/Resonance/Bubble/
Switch discriminator. Prints, per cell: current classified type, then colour
features of the die face and its centre (pip) region."""
import numpy as np, cv2
from PIL import Image
from rdom.capture.live import LiveGrabber
from rdom.perception.board import (load_templates, classify_type, cell_box,
                                   COLS, ROWS, _debuff_cast)

g = LiveGrabber(); f = g.grab(); g.close()
Image.fromarray(f).save(r'C:\dev\rdom\_colors.png')
f = _debuff_cast(f); H, W = f.shape[:2]
tpls = load_templates()


def feats(crop):
    h, w = crop.shape[:2]
    m = 0.20
    face = crop[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    Hh, Ss, Vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sat = Ss > 60                       # coloured (non-white) pixels only
    # centre pip region
    ch, cw = face.shape[:2]
    c = face[int(ch*0.30):int(ch*0.70), int(cw*0.30):int(cw*0.70)]
    chsv = cv2.cvtColor(c, cv2.COLOR_RGB2HSV)
    csat = chsv[..., 1] > 60
    def frac(cond): return float(cond.mean())
    green = (Hh >= 40) & (Hh <= 90) & sat
    magenta = ((Hh >= 140) | (Hh <= 5)) & sat
    cyan = (Hh >= 90) & (Hh <= 110) & sat
    purple = (Hh >= 115) & (Hh <= 140) & sat
    blue = (Hh >= 100) & (Hh <= 130) & sat
    cgreen = (chsv[..., 0] >= 40) & (chsv[..., 0] <= 90) & csat
    cpurple = (chsv[..., 0] >= 115) & (chsv[..., 0] <= 145) & csat
    return (f"grn={frac(green):.2f} mag={frac(magenta):.2f} cyn={frac(cyan):.2f} "
            f"pur={frac(purple):.2f} blu={frac(blue):.2f} | "
            f"Cgrn={frac(cgreen):.2f} Cpur={frac(cpurple):.2f} "
            f"white={frac((Vv>195)&(Ss<60)):.2f}")


i = 0
for rv in ROWS:
    for cu in COLS:
        x0, y0, x1, y1 = cell_box(cu, rv, W, H)
        crop = f[y0:y1, x0:x1]
        dt, sc = classify_type(crop, tpls)
        print(f"#{i+1:2d} {dt:9s} {feats(crop)}")
        i += 1
