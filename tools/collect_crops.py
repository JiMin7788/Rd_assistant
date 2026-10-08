"""Collect labelled die crops for training the learned recogniser.

Runs during a battle: taps Summon to keep the board changing, grabs frames, cuts
the 15 cells, and saves each crop. Cells the colour rules are VERY confident about
are auto-labelled into data/crops/<label>/; ambiguous ones (the Light/Bubble grey
zone we need the model for) go to data/crops/_unlabeled/ for manual sorting.

  python tools/collect_crops.py 200        # ~200 frames

dxcam: only this process grabs -- do not run another grabber alongside.
"""
import sys, time, uuid, os
import numpy as np
import cv2
from PIL import Image
from rdom.capture.live import LiveGrabber
from rdom.perception.board import (cell_box, COLS, ROWS, _debuff_cast, is_battle,
                                   is_game_over, _dark_frac, _bright_frac)
from rdom.input.inject import Injector, SUMMON_UV, SPEED_UV

ROOT = r"C:\dev\rdom\data\crops"


def strict_label(crop):
    """Confident colour-rule label, or None if ambiguous (needs the model/manual)."""
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
    if _bright_frac(crop) < 0.10 and max(tan, green, pink) < 0.05:
        return "empty"
    if tan >= 0.20 or btan >= 0.35:              # unmistakable tan wooden frame
        return "Predator"
    if green >= 0.35 or bgreen >= 0.42:          # unmistakable green face
        return "Resonance"
    if pink >= 0.10:                             # unmistakable pink arrows
        return "Switch"
    if bw >= 0.65 and darkblue < 0.03:           # clear white star cloud
        return "Light"
    if bw < 0.12 or darkblue >= 0.22:            # clear dark blue gem
        return "Bubble"
    return None                                  # ambiguous -> manual


def main():
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    for c in ("Predator", "Light", "Resonance", "Bubble", "Switch", "empty", "Bomb",
              "_unlabeled"):
        os.makedirs(os.path.join(ROOT, c), exist_ok=True)
    g = LiveGrabber(); inj = Injector(execute=True)
    inj.tap(*SPEED_UV); time.sleep(0.4)
    counts = {}
    for k in range(n_frames):
        if g.window_moved():
            print("window moved -- stop"); break
        raw = g.grab()
        if is_game_over(raw):
            print("game over -- stop"); break
        if not is_battle(raw):
            inj.tap(0.50, 0.62); time.sleep(0.8); continue
        inj.tap(*SUMMON_UV)
        f = _debuff_cast(raw); H, W = f.shape[:2]
        for rv in ROWS:
            for cu in COLS:
                x0, y0, x1, y1 = cell_box(cu, rv, W, H)
                crop = f[y0:y1, x0:x1]
                lab = strict_label(crop) or "_unlabeled"
                uid = uuid.uuid4().hex[:10]
                Image.fromarray(crop).save(os.path.join(ROOT, lab, uid + ".png"))
                counts[lab] = counts.get(lab, 0) + 1
        if k % 20 == 0:
            print(f"[{k}] {counts}", flush=True)
        time.sleep(0.7)
    g.close()
    print("DONE", counts)


if __name__ == "__main__":
    main()
