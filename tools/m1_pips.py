"""M1 pip counter: count pip dots on each of the 15 board cells.

A pip renders as a small, round, locally-dark dot on the die face -- purple on
Predator/Light/Bubble, green on Resonance, and darker than whatever face color
it sits on. Detecting "dark round blob" unifies all themes and rejects the
Predator number strokes (not round) and glow streaks. Count = pip level.
"""
from __future__ import annotations
import sys, numpy as np, cv2
from PIL import Image, ImageDraw

COLS = [0.284, 0.390, 0.499, 0.610, 0.717]
ROWS = [0.551, 0.621, 0.690]
# ground truth for the reference frame (session _0747_ab15 f7000), for scoring
TRUTH = {1:1,2:1,3:1,4:1,5:1,6:1,7:2,8:1,9:1,10:1,11:1,12:1,13:2,14:1,15:1}

def count_pips(cell_rgb):
    h, w = cell_rgb.shape[:2]
    m = 0.20
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    area = face.shape[0] * face.shape[1]

    def round_blobs(mask):
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        n = 0
        for c in cnts:
            a = cv2.contourArea(c)
            if a < 0.004 * area or a > 0.09 * area:
                continue
            p = cv2.arcLength(c, True)
            if p and 4 * np.pi * a / (p * p) >= 0.55:
                n += 1
        return n

    # (a) coloured pip: purple or green, saturated, not a bright highlight
    purple = (H >= 95) & (H <= 155)
    green = (H >= 42) & (H <= 92)
    colored = ((purple | green) & (S > 85) & (V < np.percentile(V, 55))).astype(np.uint8)
    n = round_blobs(colored)
    if n:
        return n
    # (b) no coloured pip -> Predator's neutral dark central dot
    neutral = ((S < 75) & (V < np.percentile(V, 18))).astype(np.uint8)
    return round_blobs(neutral)

def main():
    frame = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "m1_pips_out.png"
    img = Image.open(frame).convert("RGB"); W, H = img.size
    arr = np.array(img)
    hw, hh = int(0.050 * W), int(0.034 * H)
    cell = 150
    sheet = Image.new("RGB", (cell * 5, cell * 3 + 20), (30, 30, 35))
    dr = ImageDraw.Draw(sheet)
    correct = 0
    i = 0
    for rv in ROWS:
        for cu in COLS:
            cx, cy = int(cu * W), int(rv * H)
            box = (cx - hw, cy - hh, cx + hw, cy + hh)
            c = count_pips(arr[box[1]:box[3], box[0]:box[2]])
            t = TRUTH.get(i + 1)
            ok = (t == c)
            correct += ok
            r, cc = i // 5, i % 5
            px, py = cc * cell + 4, r * cell + 4
            sheet.paste(img.crop(box).resize((cell - 8, cell - 30)), (px, py))
            col = (120, 255, 120) if ok else (255, 120, 120)
            dr.text((px + 2, py + cell - 26), f"#{i+1} p={c} (t{t})", fill=col)
            print(f"  #{i+1:2d}  pip={c}  truth={t}  {'OK' if ok else 'X'}")
            i += 1
    sheet.save(out)
    print(f"pip accuracy: {correct}/15")
    print("wrote", out)

if __name__ == "__main__":
    main()
