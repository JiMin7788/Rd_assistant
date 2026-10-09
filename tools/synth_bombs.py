"""Synthesise Bomb training crops (no real gear-deck bomb has been recorded yet).

The bomb sprite (assets/templates/dice/dice_bomb*.png) is pasted onto real empty
board tiles with the perspective/scale/brightness jitter of real dice, at the
72 px training scale. Saved to data/crops_gear/_raw/bomb_syn_XXXX.png with
y_bomb.npy = "Bomb". Replace with real crops as soon as a game shows bombs.

  python tools/synth_bombs.py --n 2000
"""
import argparse, os, sys
import numpy as np, cv2
from PIL import Image
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=2000); a = ap.parse_args()
D = r"C:\dev\rdom\data\crops_gear"; rng = np.random.RandomState(0)
sprites = [np.array(Image.open(rf"C:\dev\rdom\assets\templates\dice\dice_bomb{k}.png").convert("RGBA")) for k in (1, 2, 3)]
bg = []
for tag in ("s4", "s5", "s6", "s7", "s8", "s9"):        # empty tiles as predicted (high-res review pass)
    names = np.load(os.path.join(D, f"feats_{tag}.npz"))["names"]
    T = np.load(os.path.join(D, "review_3", f"pred_{tag}.npz"), allow_pickle=True)["T"]
    bg += list(names[T == "empty"])
print("empty tiles", len(bg))
names = []
for k in range(a.n):
    tile = cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", bg[rng.randint(len(bg))] + ".png")), cv2.COLOR_BGR2RGB).astype(np.float32)
    sp = sprites[rng.randint(3)]
    s = rng.uniform(0.70, 0.88) * 72
    w = int(s * sp.shape[1] / sp.shape[0] * rng.uniform(0.9, 1.1)); h = int(s)
    spr = cv2.resize(sp, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    # mild perspective: squash top
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]]); d = rng.uniform(0, 0.08) * w
    dst = np.float32([[d, rng.uniform(0, 4)], [w - d, rng.uniform(0, 4)], [w, h], [0, h]])
    spr = cv2.warpPerspective(spr, cv2.getPerspectiveTransform(src, dst), (w, h))
    x0 = int((72 - w) / 2 + rng.uniform(-4, 4)); y0 = int((72 - h) / 2 + rng.uniform(-5, 3))
    x0, y0 = max(0, min(72 - w, x0)), max(0, min(72 - h, y0))
    al = spr[..., 3:4] / 255.0
    roi = tile[y0:y0+h, x0:x0+w]; tile[y0:y0+h, x0:x0+w] = roi * (1 - al) + spr[..., :3] * al
    tile = np.clip(tile * rng.uniform(0.75, 1.2) + rng.uniform(-20, 20), 0, 255).astype(np.uint8)
    n = f"bomb_syn_{k:04d}"; cv2.imwrite(os.path.join(D, "_raw", n + ".png"), cv2.cvtColor(tile, cv2.COLOR_RGB2BGR)); names.append(n)
np.savez(os.path.join(D, "feats_bomb.npz"), names=np.array(names))
np.save(os.path.join(D, "y_bomb.npy"), np.array(["Bomb"] * len(names), dtype=object))
np.save(os.path.join(D, "pip_bomb.npy"), np.zeros(len(names), int))
print("saved", len(names))
