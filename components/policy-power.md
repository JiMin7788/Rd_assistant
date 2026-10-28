---
title: Power-up order policy
type: component
updated: 2026-10-29
sources: [rdf01-t2]
---
# Power-up order policy

`policy/power.py` (under `src/rdom`) decides which power-up card (Growth / Alignment / Resonance) to buy next for the support deck. Pure functions plus a small `PowerTracker`; the player does the tapping. Not yet wired into a play loop. See [support-deck engine](policy-support.md) for the sibling engine.

## Order as built
- Growth up to `power_growth_first` (7); then Alignment:Resonance by `power_ratio` (3:1); once `power_growth_late_after` (8) Alignment/Resonance purchases are made, Growth goes on up to `power_growth_late` (8).
- Every card starts a game at Lv.1 (`INITIAL`); purchases are counted as level-1 (`pa`, `pr`).
- Ratio pick: Resonance when `pa*y >= x*(pr+1)`, else Alignment, so the sequence from A1 R1 is A A A R A A A R.
- If Alignment and Resonance are both unusable (maxed), Growth is bought up to `growth_late` regardless of the A/R count; at `growth_late` nothing is left (`None`).

## Entry points
- `next_card(levels, available, cfg)` → card or `None`; `plan_visit(levels, available, cfg, n=6)` → up to 6 taps for one panel visit, simulating each level rise.
- `load_power_config(path)` reads the `power_*` keys of `[decks.support]` in `config/deck.toml`; a missing file, bad TOML, missing table or key gives the default for it.
- `PowerTracker`: `start_visit(read)` → `(levels, src, lines)`, `tapped(seq)`, `available()`, `record()`, static `line(seq, levels, src)`.

## Pitfalls
- Taps without enough SP do nothing, so the order is recomputed from card levels at every panel visit, never from tap history alone. A level read from the screen replaces the count; an unread level is last read plus taps since (`src` `count` instead of `read`).
- Maxed detection: a card is maxed only after 2 strikes. A strike needs the card tapped last visit, read both now and the visit before, not risen while another tapped card did rise (if nothing rose, SP was missing, which proves nothing). A rise resets strikes.
- The module imports stdlib only (a test enforces `__future__`, `dataclasses`, `tomllib`, `math`).
- The `power_*` keys sit in `[decks.support]`, which must stay after `[decks.decay]` (see [support-deck engine](policy-support.md)).

## Evidence
- commit `5359adb` — adds the power-up module (power.py in the policy package: `next_card`, `PowerTracker`), its tests (test_policy_power) and the `power_*` keys; cited by commit because the files are not yet in the main checkout
- `config/deck.toml` — `power_growth_first`, `power_ratio`, `power_growth_late`, `power_growth_late_after` under `[decks.support]`
