"""300-trial backtest + algorithm optimisation.

Metric = SKILL (Cheong destroy) casts, the bottleneck. Two scenarios:
  build     - empty board -> target
  recovery  - complete board hit by a field-change effect (k cells scrambled)
              -> back to target, with vs without a reserved switch.
"""
import random
from rdom.sim.board_sim import SimBoard, disrupt, is_complete, DECK
from rdom.sim.planner import solve, _realize, classify

TRIALS = 300


def build_bench(mode, weights=None, trials=TRIALS):
    sk = su = mg = fails = worst = 0
    for seed in range(trials):
        b = SimBoard(seed=seed, summon_weights=weights)
        r = solve(b, mode=mode)
        if not r["complete_inventory"]:
            fails += 1; continue
        sk += r["skills"]; su += r["summons"]; mg += r["merges"]
        worst = max(worst, r["skills"])
    n = trials - fails
    return dict(mode=mode, avg_skill=round(sk/n, 2), avg_summon=round(su/n, 1),
                avg_merge=round(mg/n, 1), worst=worst, fails=fails)


def recovery_bench(k, keep_switch, mode="min_skill", trials=TRIALS):
    """Build to target, scramble k cells, measure skills to recover."""
    sk = fails = worst = 0
    for seed in range(trials):
        rng = random.Random(10000 + seed)
        b = SimBoard(seed=seed)
        solve(b, mode=mode)                      # reach target
        # optionally guarantee a reserved pip-1 switch sits in a don't-care cell
        if keep_switch and not any(c and c[0] == "Switch" and c[1] == 1 for c in b.cells):
            for i, c in enumerate(b.cells):
                from rdom.sim.board_sim import FIXED, NCELLS
                if (i + 1) in NCELLS and c and c[0] not in ("Bubble", "Resonance"):
                    b.cells[i] = ("Switch", 1); break
        b.cells = disrupt(b.cells, k, rng)       # field-change hit
        b.skills = 0                             # count only recovery skills
        r = solve(b, mode=mode)
        if not r["complete_inventory"]:
            fails += 1; continue
        sk += b.skills; worst = max(worst, b.skills)
    n = trials - fails
    return dict(k=k, keep_switch=keep_switch, avg_skill=round(sk/n, 2),
                worst=worst, fails=fails)


if __name__ == "__main__":
    print(f"=== BUILD (empty -> target), {TRIALS} trials, metric = skill casts ===")
    for mode in ("destroy_only", "min_skill", "eager"):
        r = build_bench(mode)
        print(f"  {r['mode']:12} avg_skill={r['avg_skill']:5}  "
              f"summon={r['avg_summon']:5}  merge={r['avg_merge']:4}  worst={r['worst']}")
    r = build_bench("eager", weights=[3, 5, 3, 1, 1])
    print(f"  {'eager+biased':12} avg_skill={r['avg_skill']:5}  "
          f"summon={r['avg_summon']:5}  merge={r['avg_merge']:4}  worst={r['worst']}")

    print(f"\n=== RECOVERY (target -> field-change k cells -> target), {TRIALS} trials ===")
    for k in (2, 3, 5):
        a = recovery_bench(k, keep_switch=False)
        b = recovery_bench(k, keep_switch=True)
        print(f"  k={k}: no-reserve avg_skill={a['avg_skill']:5} | "
              f"reserve-switch avg_skill={b['avg_skill']:5}")
