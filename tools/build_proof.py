"""Full-build convergence proof: from an EMPTY board, drive the live planner
(plan_next) on the faithful SimBoard through summon / switch / merge_destroy /
destroy until the exact target layout is built -- Predator #1,#3,#11 and Light
#2,#6,#7,#8,#12 exact, plus >=1 bubble and >=3 resonance in the n-cells.

Mimics live perception by forcing pip=1 in the board dicts handed to the planner
(the pip-1 deck assumption). Verifies (a) it converges, and (b) it does NOT churn
-- once fixed cells are placed they stay placed (max fixed == final fixed)."""
import random
from rdom.sim.board_sim import SimBoard, FIXED, is_complete
from rdom.policy.target import plan_next, evaluate

STEP_CAP = 4000


def to_board(cells):
    return [{"cell": i + 1,
             "type": "empty" if c is None else c[0],
             "pip": 0 if c is None else 1}          # perception forces pip 1
            for i, c in enumerate(cells)]


def fixed_ok(cells):
    return sum(1 for cell, want in FIXED.items()
               if cells[cell - 1] is not None and cells[cell - 1][0] == want)


def positions_exact(cells):
    return fixed_ok(cells) == len(FIXED)


def run(seed):
    b = SimBoard(seed=seed)
    max_fixed = 0
    regress = 0
    for step in range(STEP_CAP):
        board = to_board(b.cells)
        f = fixed_ok(b.cells)
        if f < max_fixed:
            regress += 1
        max_fixed = max(max_fixed, f)
        if evaluate(board)["complete"] and positions_exact(b.cells):
            return True, step, max_fixed, regress
        a = plan_next(board, cheong_ready=True, switch_ready=True)
        if not a:
            break
        op = a["op"]
        if op == "summon":
            if b.summon() is None:
                break
        elif op == "switch":
            b.swap(a["from"] - 1, a["to"] - 1)
        elif op == "merge":
            b.merge(a["from"] - 1, a["to"] - 1)
        elif op == "merge_destroy":
            b.merge(a["from"] - 1, a["to"] - 1)
            b.destroy(a["to"] - 1)              # remove the pip-2 result
        elif op == "destroy":
            b.destroy(a["cell"] - 1)
        else:                                   # wait/no-op with nothing to do -> stuck
            break
    return False, STEP_CAP, max_fixed, regress


if __name__ == "__main__":
    N = 200
    wins = steps = skills = regressers = 0
    fails = []
    for s in range(N):
        ok, st, mf, rg = run(s)
        if ok:
            wins += 1; steps += st
        else:
            fails.append((s, mf))
        if rg > 0:
            regressers += 1
    print(f"Full-build convergence -- {N} games from empty (step cap {STEP_CAP})")
    print(f"  converged: {wins}/{N} ({100*wins/N:.1f}%)   avg steps {steps/max(wins,1):.0f}")
    print(f"  games with any fixed-cell regression (churn): {regressers}/{N}")
    if fails:
        print(f"  failed (seed, max_fixed reached): {fails[:8]}")
