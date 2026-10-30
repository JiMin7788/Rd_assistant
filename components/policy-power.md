---
title: Power-up order policy
type: component
updated: 2026-10-30
sources: [rdf01-t2, rdf01-i1, rdf03-t5]
---
# Power-up order policy

`policy/power.py` (under `src/rdom`) decides which power-up card (Growth / Alignment / Resonance) to buy next for the support deck. Pure functions plus a small `PowerTracker`; `PlayPlayer` in `tools/support_players.py` does the tapping. See [support-deck engine](policy-support.md) for the sibling engine.

## Order as built
- Growth up to `power_growth_first` (7); then Alignment:Resonance by `power_ratio` (3:1); once `power_growth_late_after` (8) Alignment/Resonance purchases are made, Growth goes on up to `power_growth_late` (8).
- Every card starts a game at Lv.1 (`INITIAL`); purchases are counted as level-1 (`pa`, `pr`).
- Ratio pick: Resonance when `pa*y >= x*(pr+1)`, else Alignment, so the sequence from A1 R1 is A A A R A A A R.
- If Alignment and Resonance are both unusable (maxed), Growth is bought up to `growth_late` regardless of the A/R count; at `growth_late` nothing is left (`None`).

## SP reserve
- `keep(cost, cfg)` = `reserve_x * cost` (`power_reserve_x`, default 3, in `[decks.support]`): power-ups may spend only SP above it, the rest is kept for summons. `cost` is the summon cost read by `perception/sp.py` (see [score reader](perception-score.md)).
- Only the policy side exists so far: `PlayPlayer` still passes `sp=None, keep=None` (log shows `SP ?, keep ?`) until rdf03-t6 reads SP/prices.

## Entry points
- `next_card(levels, available, cfg)` → card or `None`; `plan_visit(levels, available, cfg, n=6)` → up to 6 taps for one panel visit, simulating each level rise.
- `load_power_config(path)` reads the `power_*` keys of `[decks.support]` in `config/deck.toml`; a missing file, bad TOML, missing table or key gives the default for it.
- `PowerTracker` (per game): `levels()`, `start_visit(read, found=None)` → `Lv check` log lines, `confirmed(card, price)`, `not_confirmed(card, affordable, sp_known)` → new maxed lines, `last_price(card)`, `available()`, `record()`, static `line(taps, levels, sp, keep, bought)`.

## Levels are a count, screen digits only cross-check
- Level = `INITIAL` + purchases the game *confirmed* (SP drop or level change, reported through `confirmed`). Read digits never change it.
- `start_visit` compares read digits with the count and returns one of: `Lv check: read G2 A1 R1 = count`, `... = count +1 on every card (field effect)` (at least two cards read and all exactly one above the count: a per-game field effect, detected, never assumed), `Lv check: <card> read N, count M (count kept)`, or `Lv check: not read`. A card not found on the panel counts as not read.
- `record()` (R14 `power`) is `None` before the first visit, else `levels`, `src` (always `count`), `maxed`, `bought`, `unconfirmed`, `visits`, `lv_check` (ok/field/mismatch/unread counters) and `price`. Levels are never `None` any more.

## Maxed detection
- A tap that is not confirmed is a strike only when SP was known and enough (`affordable and sp_known`); a missing or short SP proves nothing and adds none. Two strikes in a row make the card maxed (`power card X maxed at Lv N`); a confirmed buy resets the strikes.

## Pitfalls
- Interim in `PlayPlayer`: until rdf03-t6, every tap is recorded as `confirmed(card, None)`, so levels behave like the old tap counting and a screen Lv of 7 with count 1 just logs a mismatch and still buys Growth.
- The module imports stdlib only (a test enforces `__future__`, `dataclasses`, `tomllib`, `math`).
- The `power_*` keys sit in `[decks.support]`, which must stay after `[decks.decay]` (see [support-deck engine](policy-support.md)).

## Evidence
- commit `93dbaf2` — power.py (`keep`, `reserve_x`, count-based `PowerTracker`, `Lv check` lines, strike rule), `PlayPlayer` interim `confirmed(c, None)` with AI-NOTE in tools/support_players.py, tests `test_lv_check_field_effect_leaves_levels`, `test_no_strike_when_not_affordable_or_sp_unknown`, `test_keep_and_reserve_config`, `test_record_shape`; cited by commit because the task branch is not yet merged into the main checkout
- commit `5359adb` — original power-up module and `power_*` keys (superseded tracker design)
- `config/deck.toml` — `power_growth_first`, `power_ratio`, `power_growth_late`, `power_growth_late_after` under `[decks.support]`
