"""Offline dry run for the support deck: frame -> read board -> evaluate -> plan -> score.
Nothing is injected and no game is needed. Usage: python tools/support_dryrun.py [--data-dir <dir>] <frame.png>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.score import read_score
from rdom.perception.sp import read_sp, read_summon_cost
from rdom.perception.support import read_board_support
from rdom.policy.support import evaluate_support, plan_support


USAGE = "usage: python tools/support_dryrun.py [--data-dir <dir>] <frame.png>"


def dryrun(frame_rgb):
    """Report lines for one RGB frame: board rows, evaluation, planned action, score, SP, summon cost."""
    board = read_board_support(frame_rgb)
    lines = []
    for r in range(3):
        row = board[r * 5:(r + 1) * 5]
        lines.append("  ".join(f"#{c['cell']} {c['type']} {c['pip']}" for c in row))
    lines.append(f"evaluate: {evaluate_support(board)}")
    # AI-NOTE: support_ready=True so the supporter branch of the plan is visible offline
    lines.append(f"planned action: {plan_support(board, support_ready=True)}")
    lines.append(f"score: {read_score(frame_rgb)}")
    lines.append(f"sp: {read_sp(frame_rgb)}")
    lines.append(f"summon cost: {read_summon_cost(frame_rgb)}")
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["--help"], ["-h"]):                # AI-NOTE: otherwise '--help' was opened as an image path
        print(USAGE)
        return 0
    data_dir = None
    if len(argv) == 3 and argv[0] == "--data-dir":
        data_dir, argv = argv[1], argv[2:]
    if len(argv) != 1:
        print(USAGE)
        return 2
    if data_dir is not None:
        # AI-NOTE: the support nets and the gear pip fallback both read gear._DATA; cached nets of the old dir must go
        from rdom.perception import gear, support
        gear._DATA = support._DATA = data_dir
        support._models.clear()
    import numpy as np
    from PIL import Image
    img = np.array(Image.open(argv[0]).convert("RGB"))
    print("\n".join(dryrun(img)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
