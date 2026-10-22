---
title: Rule-based bot, no BC/RL (2026-09-16)
type: decision
updated: 2026-10-23
sources: [seed]
---
# Rule-based bot, no BC/RL (2026-09-16)

User decision 2026-09-16: no deep-learned policy. The end state is a rule-based bot = perception (M1)
+ input (M2) + a rule engine that executes the user's written strategy (M3).

## Context
`docs/00_PRE_RESEARCH.md` planned recording 10–30 h of play for behaviour cloning / RL; the recorder
(`src/rdom/recorder/`, `docs/03_RECORDER_SPEC.md`) was built for that.

## Choice and consequences
- Dropped: M5 (BC), M6 (simulator for RL), M7 (RL); no bulk data collection. The ~109 min of three
  existing sessions are the M1 real-frame source.
- A small placement simulator survived as a planning tool (`src/rdom/sim/`, backtests), not for RL.
- Dataset builder shrinks to "extract frames/crops for recognition"; R6 calibration lost priority.
- Supervised recognizers (sklearn, later small CNNs for gear type/pip) are still used — the "no deep
  learning" applies to the policy, not to perception.
- Input injection became central, so the ToS/operating-scope question (`docs/00_PRE_RESEARCH.md` §6:
  PvE only vs coop) had to be decided first.

## Evidence
- `CLAUDE_CODE_TODO.md` — "방향 결정 (2026-09-16, 사용자)" block
- `src/rdom/sim/planner.py`, `tools/sim_backtest.py` — surviving simulator
- `tools/train_gear_type_cnn.py`, `tools/train_gear_pip_cnn.py` — perception models (not policy)
- `docs/00_PRE_RESEARCH.md` — §4.3 learning options, §6 ToS risk
