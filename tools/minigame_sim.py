"""Offline regression run of the gauge loop on a simulated game (our own model, not the real game).

    python tools/minigame_sim.py --case gpg --gauges 104 --seed 1

Prints 'sim <case>: 노랑 <y>/<n> (<pct>%)' and the latency the loop ended with. The sim only checks that the
loop still behaves under OUR assumptions of the game (frame clock, input latency, capture delay); it says
nothing about the real game (see src/rdom/sim/gauge_sim.py). Touches no window, no input, no files.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import minigame_bot  # noqa: E402
from rdom.sim.gauge_sim import CASES, run_case  # noqa: E402

RESULT_LINE = "sim {case}: 노랑 {y}/{n} ({pct}%)"
LATENCY_LINE = "지연 추정: {est} ms (시뮬 설정 {true} ms, 시작값 {guess} ms)"


def main(argv=None, out=print):
    ap = argparse.ArgumentParser(prog="minigame_sim", description="Gauge loop on a simulated game.")
    ap.add_argument("--case", choices=sorted(CASES), required=True)
    ap.add_argument("--gauges", type=int, default=104)
    ap.add_argument("--seed", type=int, default=1)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    run = run_case(minigame_bot, a.case, a.gauges, a.seed)
    n = len(run.results)
    y = run.yellow()
    out(RESULT_LINE.format(case=a.case, y=y, n=n, pct=f"{100.0 * y / n:.0f}" if n else "0"))
    c = run.case
    out(LATENCY_LINE.format(est=round(run.cal.estimate() * 1000), true=round(c.latency * 1000),
                            guess=round(c.guess * 1000)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
