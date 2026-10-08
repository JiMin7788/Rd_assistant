"""Record what the placement bot WANTS to do, without acting (dry). For each of
N frames: read the board, plan the next action, and save an annotated frame
(cell type/pip labels + an arrow for the planned from->to drag). Lets us see
whether the drags make sense or the recognition is wrong.
"""
import sys, time
import numpy as np
from PIL import Image, ImageDraw
from rdom.capture.live import LiveGrabber
from rdom.perception.board import read_board, load_templates, COLS, ROWS, HALF_W, HALF_H
from rdom.policy.target import plan_next, evaluate

N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
g = LiveGrabber(); tpls = load_templates()
for i in range(N):
    f = g.grab(); H, W = f.shape[:2]
    board = read_board(f, tpls)
    ev = evaluate(board)
    action = plan_next(board, cheong_ready=True, switch_ready=True)
    im = Image.fromarray(f); dr = ImageDraw.Draw(im)
    hw, hh = int(HALF_W * W), int(HALF_H * H)
    def ctr(n):
        r, c = (n-1) // 5, (n-1) % 5
        return int(COLS[c]*W), int(ROWS[r]*H)
    for c in board:
        cx, cy = ctr(c["cell"])
        dr.rectangle([cx-hw, cy-hh, cx+hw, cy+hh], outline=(0, 255, 0), width=2)
        lab = "·" if c["type"] == "empty" else f"{c['type'][:2]}{c['pip']}"
        dr.text((cx-hw+2, cy-hh+2), f"{c['cell']}:{lab}", fill=(255, 255, 0))
    if action and action.get("from") and action.get("to"):
        a = ctr(action["from"]); b = ctr(action["to"])
        dr.line([a, b], fill=(255, 0, 0), width=5)
        dr.ellipse([b[0]-10, b[1]-10, b[0]+10, b[1]+10], outline=(255, 0, 0), width=4)
    dr.text((20, 20), f"{action}", fill=(255, 0, 255))
    im.save(rf'C:\dev\rdom\_diag_{i}.png')
    row = "  ".join(f"{c['type'][:2]}{c['pip']}" for c in board)
    print(f"[{i}] complete={ev['complete']} action={action}")
    print(f"    {row}")
    time.sleep(2.0)
g.close()
