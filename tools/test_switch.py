"""Empirically test whether a switch drag actually swaps two cells in-game."""
import time
from rdom.capture.live import LiveGrabber
from rdom.perception.board import read_board_stable, load_templates
from rdom.input.inject import Injector, cell_uv
from PIL import Image

g = LiveGrabber(); tpls = load_templates(); inj = Injector(execute=True)
b = read_board_stable(g, tpls)
types = [c["type"] for c in b]
print("before:", " ".join(f"{i+1}:{t[:2]}" for i, t in enumerate(types)))
Image.fromarray(g.grab()).save(r"C:\dev\rdom\_sw_before.png")

sw = next((i + 1 for i, t in enumerate(types) if t == "Switch"), None)
tgt = next((i + 1 for i, t in enumerate(types)
            if t not in ("Switch", "empty", "Bomb")), None)
print("switch cell:", sw, " target cell:", tgt)
if sw and tgt:
    ua, va = cell_uv(sw); ub, vb = cell_uv(tgt)
    print(f"drag switch #{sw}({types[sw-1]}) -> #{tgt}({types[tgt-1]})")
    inj.swipe(ua, va, ub, vb)
    time.sleep(1.0)
    b2 = read_board_stable(g, tpls)
    t2 = [c["type"] for c in b2]
    print("after: ", " ".join(f"{i+1}:{t[:2]}" for i, t in enumerate(t2)))
    print(f"cell #{sw}: {types[sw-1]} -> {t2[sw-1]}   cell #{tgt}: {types[tgt-1]} -> {t2[tgt-1]}")
    swapped = (t2[sw-1] == types[tgt-1] and t2[tgt-1] == types[sw-1])
    print("SWAPPED!" if swapped else "no swap (positions unchanged or rejected)")
    Image.fromarray(g.grab()).save(r"C:\dev\rdom\_sw_after.png")
g.close()
