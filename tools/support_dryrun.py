"""Offline dry run for the support deck: frame -> read board -> evaluate -> plan -> score.
Nothing is injected and no game is needed. Usage: python tools/support_dryrun.py <frame.png>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.score import read_score
from rdom.perception.support import read_board_support
from rdom.policy.support import evaluate_support, plan_support


def dryrun(frame_rgb):
    """Report lines for one RGB frame: board rows, evaluation, planned action, score."""
    board = read_board_support(frame_rgb)
    lines = []
    for r in range(3):
        row = board[r * 5:(r + 1) * 5]
        lines.append("  ".join(f"#{c['cell']} {c['type']} {c['pip']}" for c in row))
    lines.append(f"evaluate: {evaluate_support(board)}")
    # AI-NOTE: support_ready=True so the supporter branch of the plan is visible offline
    lines.append(f"planned action: {plan_support(board, support_ready=True)}")
    lines.append(f"score: {read_score(frame_rgb)}")
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python tools/support_dryrun.py <frame.png>")
        return 2
    import numpy as np
    from PIL import Image
    img = np.array(Image.open(argv[0]).convert("RGB"))
    print("\n".join(dryrun(img)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
