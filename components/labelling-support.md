---
title: Support-deck labelling tools
type: component
updated: 2026-10-29
sources: [rdf01-t7, rdf01-r3-s23]
---
# Support-deck labelling tools

Offline pipeline that turns collected support crops (`data/crops_support`) into training tags: pre-label, human sheet review, tag build. Nothing here runs at bot runtime.

## Flow
1. `tools/support_prelabel.py` writes `prelabels.jsonl` `{name, type, pip, src, ambiguous, star_cand}` for every `crops.jsonl` row that has a `_raw` PNG.
   - Type = gear type model label if in Bubble/Adjust/Growth/empty/junk/Crystal/Joker with conf >= 0.90 (src `gear-model`); else `_colour_label` (src `colour`); else `?` (src `none`). Colour and `?` crops are `ambiguous`.
   - `_colour_label` (centre half of crop, HSV): green hue 35-85 -> Resonance; dark -> Alignment; yellow hue 15-35 -> Alignment. It lives only in this tool and must never enter `src/rdom` (hue bands misread under battle effects; see [recognition pitfalls](../lessons/recognition-pitfalls.md)).
   - `gear.set_deck("doom")` is called first so `predict_types` applies no Decay remap. Pips come from `gear.predict_pips` for non-`NO_PIP` types.
   - `star_cand` = `support.star_prob` on the `_hires` crop > 0.3, or, in the same (game, cell) time sequence, a pip-6 crop followed by a crop whose pip is not 6 (a 7 star the pip net cannot see).
2. `tools/support_review.py` cuts sheets of 50 (10x5 tiles of 128 px, caption `#idx Type pip`, font shrunk so the pip digit is not clipped). One pre-label type per sheet, star candidates on their own sheets.
   - `--ambiguous` -> `review/amb/`. Ticked sheets are kept; unticked ones are deleted and re-cut under new sheet numbers (numbers are never reused, so an old `fixes.tsv` line cannot hit a different crop).
   - After cutting, `--ambiguous` prints `ambiguous: sheets N crops M`, then one line per newly cut sheet (`review/amb/sheet_NN.png`, sorted) and the `review/amb/index.tsv` path. Only sheets cut this run are listed, not kept ticked ones.
   - `--holdout g1[,g2] --n 1000` -> `review/hold_<g1>+<g2>/`, seed 0: up to 250 Resonance, 250 Alignment, 150 star candidates, then random fill to n. Refuses to overwrite an existing index/fixes unless `--force` (old fixes.tsv moved to `fixes.tsv.old`).
3. The human writes `fixes.tsv` beside `index.tsv`: `sheet_NN:<idx>\t<Type>\t<pip>`, `sheet_NN:<idx>\tdrop`, `sheet_NN\tok`.
4. `tools/build_support_tag.py --tag T [--games ...]` writes `feats_T.npz` (names) plus `y_ pip_ grp_ eff_ chk_` `.npy`. `chk` is true only for crops on an `ok` sheet; they take the label the sheet *showed* (from `index.tsv`, not the current prelabels) unless a fix changes it. Unchecked crops keep pre-label or fix with chk false. `?` and dropped crops are excluded. Prints `<tag> <n> {counts}` and `fix rate <Type> <fixed>/<checked>`.

## Gotchas
- Colour-labelled crops are pre-labels only; the gate (t8) reads chk-true crops only (spec R7).
- A tick on a sheet beats the same crop on an unticked sheet in another review dir.

## Evidence
- commit `9cd9078` — adds tools/support_prelabel.py (thresholds, `_colour_label`, `set_deck("doom")`, star_cand rules), tools/support_review.py (sheet geometry, `_cut` grouping, `ambiguous` renumbering, `holdout` caps/seed/--force), tools/build_support_tag.py (`_review`, chk and fix-rate logic, output arrays) and tests/test_support_labels.py (synthetic-crop tests).
- commit `738eaa2` — tools/support_review.py `main` prints sheet and index.tsv paths; tests/test_support_labels.py `test_ambiguous_prints_sheet_paths` asserts the lines.
- `wiki/lessons/recognition-pitfalls.md` — hue-band rules misread under effects.
