"""End-to-end dry run: frame -> read board -> evaluate vs target -> plan action.
Nothing is injected (Injector execute=False). Usage: python tools/bot_dryrun.py <frame.png>
"""
import sys
import numpy as np
from PIL import Image

from rdom.perception.board import read_board
from rdom.policy.target import evaluate, plan_next
from rdom.input.inject import Injector

frame = sys.argv[1]
img = np.array(Image.open(frame).convert("RGB"))
board = read_board(img)

print("board:")
for r in range(3):
    row = board[r*5:(r+1)*5]
    print("  " + "  ".join(f"#{c['cell']:2d} {c['type'][:4]:4s}{c['pip']}" for c in row))

ev = evaluate(board)
print(f"\ncomplete: {ev['complete']}   pip_target: {ev['pip_target']}")
if ev["violations"]:
    print("violations:")
    for v in ev["violations"]:
        print("  ", v)

action = plan_next(board, cheong_ready=True)
print(f"\nplanned action: {action}")
if action and action.get("op") not in (None,):
    inj = Injector(execute=False)
    print("injection (dry-run):")
    inj.execute_action(action)
