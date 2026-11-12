---
title: Rule-based policy engines (M3)
type: component
updated: 2026-11-12
sources: [seed, rdT13, rdT16]
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

## Sevens data mode (rdT16, user 2026-11-12, data first)
- Switch: `config/data_mode.toml` `sevens = true`, read by `policy/data_mode.sevens()` once per game (`gear_bot.play` start, one `PlayPlayer` per support game). Missing file, bad TOML or anything but `true` -> off and the old plans run unchanged. On: prints `data mode: sevens` once per game. The file is committed with `sevens = true`; `tests/conftest.py` points `data_mode.FILE` at a missing file for every test, so tests see the switch off unless they set it.
- `plan_next(..., sevens=True)` runs the clone_alert rule, then `_plan_sevens`: empty -> `summon`; bombs (old `_bomb_action`); `support_ready` and a pip-7 die -> `support` from that 7 (`_seven_drop`: non-gear 7 first, then the type with the most 7s, then the smaller cell; the die comes back as a 6, maybe another type); Joker copy; the legal merge with the HIGHEST pip (gear pairs allowed before 초월 too, Bubble keep-lo still holds, ties by the phase A/B score); the old Doom/Adjust/surplus supporter pool; `wait` why `no move`. No `complete` wait. Every pair touching a pip-7 die is added to `banned`, so no rule merges a 7. Also skipped in this mode: the crystal merge preference, `_surplus_merge`, the phase-B gear-average limit (`_phase_b_allowed`) and the near-complete / bridge-bubble supporter rules.
- `gear_bot.play` (sevens on): stats gain `sevens` (new pip-7 dice), `drops` (supporter swipes from a pip-7 cell), `hi_crops`; on a stable board `collect.HiWatch` finds cells whose read changed to pip 6/7 and `collect.save_cells` saves those crops (same `crops_gear/_raw` + `live_labels.jsonl` as `maybe_save`, skipped when `g.unobscured()` is False), at most once per cell per `HI_EVERY` 5 s on top of the 15 s cadence. On return it prints `gear result: <res> (merges .., fails .., support .., sevens .., drops .., hi_crops ..)`. The Discord/round record in `gear_loop.py` is unchanged.

## policy/support.py — support deck (2026-10-29)
Third engine (Resonance/Alignment/Bubble/Adjust/Growth), driven by `PlayPlayer.battle_tick` in `tools/support_players.py` ([support players](support-players.md)). See [support-deck engine](policy-support.md).

## Evidence
- commit `0720269` — adds the support-deck engine (policy/support.py)
- `src/rdom/policy/target.py` — `FIXED`, `NEED`, `PRED_PRIORITY`, docstring
- `src/rdom/policy/gear.py` — docstring, `KEEP`, `TARGET_AVG`, `load_deck`
- `tools/gear_bot.py` — docstring (tick rule order), `SUPPORT_CD = 130.0`
- `tools/gear_bot.py` — `OPENING_TICK`, `OPENING_BURST_MAX`, `OPENING_SUMMON_GAP` constants and the `stats["merges"] == 0` branches in `play()` (opening sleep, summon burst, `opening done` line)
- commit `cc1d57a` — adds the opening-phase test file (test_gear_bot_opening.py, tests dir): burst of 4 / cap 5, 0.2 s sleeps and 0.12 s gaps, support swipe keeps the opening, `opening done` once
- `tests/test_policy.py`, `tests/test_policy_gear.py`, `tests/test_sim.py`
- commit `b4ee44c` (task/rdT16) — adds the switch file data_mode.toml (config dir) and the reader data_mode.py (policy package, `sevens`); gear.py `SEVEN`, `_seven_drop`, `_plan_sevens`, `plan_next(sevens=)`; gear_bot.py `sevens`/`hi`/`_end` and the `drops` count; collect.py `HiWatch`, `HI_EVERY`, `save_cells`; tests dir conftest.py and test_sevens_mode.py (gear plan, HiWatch throttle, gear play stats and summary line, switch missing -> off). Cited by commit: the branch is not merged into the main checkout when written.
- `CLAUDE_CODE_TODO.md` — M2/M3 and simulator sections (eager = best in 300-run backtest)
