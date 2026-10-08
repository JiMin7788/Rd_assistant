"""PROOF: switch-arrangement convergence, OLD planner vs NEW planner.

Build random FULL boards that already hold the target inventory (3 predator,
5 light, 3 resonance, 1 bubble, 1 switch, +2 junk) but in random positions, then
let plan_next arrange them using only switch swaps (executed faithfully on
SimBoard). A trial SUCCEEDS iff the board reaches the exact target layout --
Predator at #1,#3,#11 and Light at #2,#6,#7,#8,#12 (100% position-accurate) plus
>=1 bubble and >=3 resonance in the n-cells -- within a step cap.

We run the SAME boards through the OLD _placement_swap (cannibalises finalised
cells -> shuffles forever) and the NEW one (locks finalised cells -> converges),
to show the fix is what makes arrangement work.
"""
import random
import rdom.policy.target as T
from rdom.sim.board_sim import SimBoard, FIXED, NCELLS, DECK, is_complete

NEW_placement_swap = T._placement_swap        # capture before any monkeypatch
STEP_CAP = 200


# ---- the OLD _placement_swap (verbatim, for the before/after contrast) --------
def OLD_placement_swap(bc):
    desired = T._desired(bc)
    switches = [c for c in range(1, 16) if bc[c]["type"] == "Switch"]
    if not switches:
        return None
    order = T.PRED_PRIORITY + [c for c in FIXED if c not in T.PRED_PRIORITY] + NCELLS
    for cell in order:
        want = desired.get(cell)
        if want is None or bc[cell]["type"] == want:
            continue
        need_pip1 = want in T.PIP1_ONLY or want == "Switch"
        src = next((c for c in range(1, 16) if c != cell
                    and bc[c]["type"] == want
                    and (not need_pip1 or bc[c]["pip"] == 1)), None)
        if src is None:
            continue
        sw_on_cell = cell if bc[cell]["type"] == "Switch" else None
        if sw_on_cell:
            if bc[sw_on_cell]["pip"] == bc[src]["pip"]:
                return (sw_on_cell, src)
        else:
            sw = switches[0]
            if bc[sw]["pip"] == bc[cell]["pip"]:
                return (sw, cell)
    return None


def cells_to_board(cells):
    return [{"cell": i + 1,
             "type": "empty" if c is None else c[0],
             "pip": 0 if c is None else c[1]}
            for i, c in enumerate(cells)]


def make_scrambled(seed):
    """Full board with the exact target inventory present but positions random."""
    rng = random.Random(seed)
    pool = ([("Predator", 1)] * 3 + [("Resonance", 1)] * 3 + [("Light", 1)] * 5
            + [("Bubble", 1)] * 1 + [("Switch", 1)] * 1)
    while len(pool) < 15:
        pool.append((rng.choice(DECK), 1))     # 2 junk dice, pip 1
    rng.shuffle(pool)
    b = SimBoard(seed=seed)
    b.cells = list(pool)
    return b


def positions_exact(cells):
    """Predator EXACTLY at #1,#3,#11 and Light EXACTLY at #2,#6,#7,#8,#12."""
    for cell, want in FIXED.items():
        c = cells[cell - 1]
        if c is None or c[0] != want:
            return False
    return True


def run_trial(seed, swap_fn):
    """Returns (converged, swaps, steps, exact_positions)."""
    T._placement_swap = swap_fn                # monkeypatch the arrange step
    b = make_scrambled(seed)
    swaps = 0
    seen = set()
    for step in range(STEP_CAP):
        if is_complete(b.cells) and positions_exact(b.cells):
            return True, swaps, step, True
        state = tuple(b.cells)
        if state in seen:                      # exact repeat -> oscillation, stuck
            return False, swaps, step, positions_exact(b.cells)
        seen.add(state)
        action = T.plan_next(cells_to_board(b.cells),
                             cheong_ready=True, switch_ready=True)
        if not action:
            break
        op = action.get("op")
        if op == "switch":
            b.swap(action["from"] - 1, action["to"] - 1); swaps += 1
        elif op == "merge":
            b.merge(action["from"] - 1, action["to"] - 1)
        elif op == "destroy":
            b.destroy(action["cell"] - 1)
        elif op == "summon":
            if b.summon() is None:
                break
        else:
            break
    ok = is_complete(b.cells) and positions_exact(b.cells)
    return ok, swaps, STEP_CAP, positions_exact(b.cells)


def summarize(name, swap_fn, seeds):
    wins = swaps_total = steps_total = 0
    fails = []
    for s in seeds:
        conv, swaps, steps, exact = run_trial(s, swap_fn)
        if conv:
            wins += 1; swaps_total += swaps; steps_total += steps
        else:
            fails.append(s)
    n = len(seeds)
    print(f"{name}: converged {wins}/{n} ({100*wins/n:.1f}%)  "
          f"avg swaps {swaps_total/max(wins,1):.1f}  avg steps {steps_total/max(wins,1):.1f}")
    if fails:
        print(f"    failed seeds (first 10): {fails[:10]}")
    return wins, n


if __name__ == "__main__":
    seeds = list(range(300))
    print(f"Arrangement convergence proof -- {len(seeds)} random scrambled boards")
    print(f"(target inventory present, positions random; step cap {STEP_CAP})\n")
    summarize("OLD (cannibalises correct cells)", OLD_placement_swap, seeds)
    summarize("NEW (locks correct cells)       ", NEW_placement_swap, seeds)
