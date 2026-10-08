"""Capture a burst of frames to catch a yellow-buff moment and measure why a
buffed Bubble reads as Predator and Light/Bubble confuse. Prints per frame: the
WB board spread (buff indicator) and each cell's type + key features."""
import time
import numpy as np, cv2
from PIL import Image
from rdom.capture.live import LiveGrabber
from rdom.perception.board import (load_templates, classify_type, cell_box, COLS,
                                   ROWS, _debuff_cast, _white_frac, _bluecyan_frac,
                                   _color_fracs)

g = LiveGrabber(); tpls = load_templates()
for shot in range(6):
    raw = g.grab()
    # buff indicator: board-region channel spread BEFORE white balance
    H, W = raw.shape[:2]
    reg = raw[int(0.50*H):int(0.72*H), int(0.20*W):int(0.78*W)].reshape(-1, 3).mean(0)
    spread = float(reg.max() - reg.min())
    f = _debuff_cast(raw)
    Image.fromarray(raw).save(rf"C:\dev\rdom\_yb{shot}.png")
    rows = []
    i = 0
    for rv in ROWS:
        for cu in COLS:
            x0, y0, x1, y1 = cell_box(cu, rv, W, H)
            crop = f[y0:y1, x0:x1]
            dt, _ = classify_type(crop, tpls)
            rows.append(f"{i+1}:{dt[:2]}")
            i += 1
    print(f"[{shot}] buff_spread={spread:5.1f}  " + " ".join(rows))
    time.sleep(1.3)
g.close()
