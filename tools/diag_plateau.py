"""One-shot plateau diagnosis: read the live board, print the grid, evaluate,
inventory counts, and what the planner wants next."""
from collections import Counter
from PIL import Image
from rdom.capture.live import LiveGrabber
from rdom.perception.board import read_board, load_templates, is_battle, is_game_over
from rdom.policy.target import evaluate, plan_next, classify

g = LiveGrabber(); f = g.grab(); g.close()
Image.fromarray(f).save(r'C:\dev\rdom\_plateau.png')
print("battle", is_battle(f), " over", is_game_over(f))
b = read_board(f, load_templates())
for r in range(3):
    print("  " + "  ".join(f"#{c['cell']:2d}{c['type'][:4]:>5}" for c in b[r*5:r*5+5]))
ev = evaluate(b)
print("complete", ev["complete"], " violations", len(ev["violations"]))
for v in ev["violations"]:
    print("   ", v)
print("type counts:", dict(Counter(c["type"] for c in b)))
keep, surplus, unmet = classify(b)
print("unmet:", unmet, " surplus cells:", surplus)
print("next action:", plan_next(b, cheong_ready=True, switch_ready=True))
