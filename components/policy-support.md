---
title: Support-deck rule engine
type: component
updated: 2026-10-29
sources: [rdf01-t1]
---
# Support-deck rule engine

`src/rdom/policy/support.py` is a pure rule engine for the support deck (Resonance/Alignment/Bubble/Adjust/Growth). `plan_support` returns one action per call; the deck values come from `[decks.support]` in `config/deck.toml`. Not yet wired into a play loop (later rdF01 tasks).

## Entry points
- `load_support_deck(path)` → `SupportDeck`; a missing file, bad TOML or a missing `[decks.support]` table gives `DEFAULT`; a missing key keeps its default.
- `evaluate_support(board, deck)` → `res7`, `align7`, `bubbles`, `empty`, `unknown`, `bombs`, `crystals`, `complete`.
- `can_merge_support(a, b)`, `plan_support(board, deck, support_ready, banned, clone_alert)`.
- Actions: `summon`, `merge {from,to}`, `support {from}`, `wait {why}`; `from` is freed, `to` becomes a random die with pip+1.

## Rules as built
- Complete = `res7` Resonance pip 7 (2) + `align7_min` Alignment pip 7 (3) + Bubbles >= keep lo (2). Merging continues after completion; `wait` has why `complete` or `no move`.
- Pip-7 dice and Growth never merge (bot policy). Adjust merges with any die of equal pip. Bomb merges only with Bomb or pip-1 Adjust.
- Order per call: empty cell → `summon`; clone_alert supporter; bomb; Joker copy (Alignment > Resonance > Bubble only while Bubbles < lo); crystal merge; best merge; supporter; wait.
- Best merge: highest pip, then Adjust paired with Resonance/Alignment over Adjust+Bubble, then landing column in `align_cols`, then smaller `to` cell. With Bubbles > keep hi the merge must consume a Bubble.
- Bubble keep: a merge may not drop Bubbles below keep lo, so with exactly 2 Bubbles none is consumed and with 3 only a one-Bubble merge (e.g. Bubble+Adjust) is allowed.
- Supporter pool (only when `support_ready`): Adjust 7, then highest Bubble while above keep hi, then Resonance 7 beyond `res7`, then a partnerless Adjust 2..6. Growth, Alignment and pip-1 dice are never chosen.
- clone_alert: a Bubble/Adjust/Joker above every Resonance/Alignment is rerolled; merges whose result would exceed the top Resonance/Alignment pip are banned.

## Pitfalls
- `[decks.support]` must stay after `[decks.decay]`: `perception.gear.deck_name()` falls back to the first deck table, which must remain doom. The top-level `force = ""` key is added but nothing reads it yet.
- It re-implements the bomb/crystal/joker rules of `policy/gear.py` instead of importing them, because those helpers read gear's global `KEEP`; it imports nothing from gear, perception, cv2, numpy or torch.
- Run its tests from a worktree with `C:\dev\rdom\.venv\Scripts\python.exe -m pytest -o pythonpath=src tests/`; without `-o pythonpath=src` the editable install tests the main checkout.

## Evidence
- commit `0720269` — adds the support-deck engine file (policy/support.py under src/rdom: `SupportDeck`/`DEFAULT`, `_best_merge`, `_supporter_pick`, clone_alert block in `plan_support`) and its tests (tests/test_policy_support.py); not yet in the main checkout when written, so it is cited by commit
- `config/deck.toml` — `force`, `[decks.support]` placed after `[decks.decay]`
- `src/rdom/perception/gear.py` — `deck_name()` falls back to the first deck table
- commit `0720269` — rdf01-t1 change
