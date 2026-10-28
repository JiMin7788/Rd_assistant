---
title: Rule-based policy engines (M3)
type: component
updated: 2026-10-23
sources: [seed]
---
# Rule-based policy engines (M3)

Two pure-function rule engines emit one action per tick: `policy/target.py` (Predator deck, fixed
layout) and `policy/gear.py` (gear deck, current production). Strategy is data from the user, not learned.

## policy/target.py — Predator deck
- Target layout and rules: `docs/02_STRATEGY.md`. `FIXED` = Predator #1 #3 #11, Light #2 #6 #7 #8 #12;
  `NEED` Predator 3, Resonance 3, Light 5, Bubble 1; reserve 1 Switch; Predator priority #1>#11>#3.
- `plan_next` = eager min-skill algorithm ported from the simulator (`src/rdom/sim/`): merge surplus
  first → summon → destroy (Cheong) last → switch arrangement. Bombs are removed first.
- Live status: runs end-to-end but did not converge to the target (switch placement open).

## policy/gear.py — gear deck (2026-10-07)
- Complete = no empty cell, kept non-gears within `KEEP` (Bubble 1–3, target 1; per-deck from
  `config/deck.toml`), every other die a Gear, all gears 4-connected, mean gear pip ≥ `TARGET_AVG` 2.2.
- Growth never merged; Doom merged when it has a partner; Adjust merges with any same-pip die.
  Phase A (before 초월) / Phase B (after) merge rules; supporter (130 s cd) rerolls a blocking die.
- Actions: `summon`, `merge {from,to}`, `support {from}`, `wait`.
- Driven by `tools/gear_bot.py` (per-tick rule order: hunt popup → 초월 → power panel → HP→SP → 사냥 → plan_next).

## policy/support.py — support deck (2026-10-29)
Third engine (Resonance/Alignment/Bubble/Adjust/Growth), not yet driven by a loop. See [support-deck engine](policy-support.md).

## Evidence
- commit `0720269` — adds the support-deck engine (policy/support.py)
- `src/rdom/policy/target.py` — `FIXED`, `NEED`, `PRED_PRIORITY`, docstring
- `src/rdom/policy/gear.py` — docstring, `KEEP`, `TARGET_AVG`, `load_deck`
- `tools/gear_bot.py` — docstring (tick rule order), `SUPPORT_CD = 130.0`
- `tests/test_policy.py`, `tests/test_policy_gear.py`, `tests/test_sim.py`
- `CLAUDE_CODE_TODO.md` — M2/M3 and simulator sections (eager = best in 300-run backtest)
