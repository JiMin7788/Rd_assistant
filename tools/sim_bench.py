"""Benchmark: how many SKILL (Cheong destroy) casts does each placement method
need? Skill is the bottleneck (90s cooldown); summon/merge are free."""
from rdom.sim.board_sim import SimBoard
from rdom.sim.planner import solve


def bench(mode, weights=None, trials=3000):
    tot_sk = tot_su = tot_mg = fails = worst = 0
    dist = {}
    for seed in range(trials):
        b = SimBoard(seed=seed, summon_weights=weights)
        r = solve(b, mode=mode)
        if not r["complete_inventory"]:
            fails += 1
            continue
        tot_sk += r["skills"]; tot_su += r["summons"]; tot_mg += r["merges"]
        worst = max(worst, r["skills"])
        dist[r["skills"]] = dist.get(r["skills"], 0) + 1
    n = trials - fails
    return {"mode": mode, "weights": "uniform" if not weights else "biased",
            "avg_skills": round(tot_sk / n, 2), "avg_summons": round(tot_su / n, 1),
            "avg_merges": round(tot_mg / n, 1), "worst_skills": worst,
            "fails": fails, "dist": dict(sorted(dist.items()))}


if __name__ == "__main__":
    print("Metric: SKILL (destroy) casts to reach the target. Lower = faster")
    print("(destroy = 90s cooldown; summon & merge are free)\n")
    rows = [bench("destroy_only"), bench("min_skill"),
            bench("min_skill", weights=[3, 5, 3, 1, 1])]  # biased summon
    print(f"{'mode':14} {'summon':8} {'avg_SKILL':>10} {'avg_summ':>9} "
          f"{'avg_merge':>10} {'worst':>6}")
    for r in rows:
        print(f"{r['mode']:14} {r['weights']:8} {r['avg_skills']:>10} "
              f"{r['avg_summons']:>9} {r['avg_merges']:>10} {r['worst_skills']:>6}")
    print("\nmin_skill skill-count distribution (uniform):", rows[1]["dist"])
