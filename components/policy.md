---
title: Rule-based policy engines (M3)
type: component
updated: 2026-11-05
sources: [seed, rdT13]
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
- Opening phase (rdT13, user 2026-11-05 '첫 합성까지 소환속도 올리기'): until the game's first merge swipe (`stats["merges"] == 0`; a support swipe does not end it) `play()` sleeps `OPENING_TICK` = 0.2 s instead of `tick` (0.6), and a `summon` action taps the summon button in one burst of `min(empty cells, OPENING_BURST_MAX)` taps (max 5), `OPENING_SUMMON_GAP` = 0.12 s apart; `SUMMON_GAP` (0.5 s) does not apply inside the burst. Taps go through the Injector, so the rdT11 lease keeps the burst in one window turn. After the first merge: normal tick, `SUMMON_GAP`, one tap. The end logs once `opening done: <n> summon taps in <s> s`. Tests: `test_gear_bot_opening.py` (commit `cc1d57a`).

## policy/support.py — support deck (2026-10-29)
Third engine (Resonance/Alignment/Bubble/Adjust/Growth), not yet driven by a loop. See [support-deck engine](policy-support.md).

## Evidence
- commit `0720269` — adds the support-deck engine (policy/support.py)
- `src/rdom/policy/target.py` — `FIXED`, `NEED`, `PRED_PRIORITY`, docstring
- `src/rdom/policy/gear.py` — docstring, `KEEP`, `TARGET_AVG`, `load_deck`
- `tools/gear_bot.py` — docstring (tick rule order), `SUPPORT_CD = 130.0`
- `tools/gear_bot.py` — `OPENING_TICK`, `OPENING_BURST_MAX`, `OPENING_SUMMON_GAP` constants and the `stats["merges"] == 0` branches in `play()` (opening sleep, summon burst, `opening done` line)
- commit `cc1d57a` — adds the opening-phase test file (test_gear_bot_opening.py, tests dir): burst of 4 / cap 5, 0.2 s sleeps and 0.12 s gaps, support swipe keeps the opening, `opening done` once
- `tests/test_policy.py`, `tests/test_policy_gear.py`, `tests/test_sim.py`
- `CLAUDE_CODE_TODO.md` — M2/M3 and simulator sections (eager = best in 300-run backtest)
