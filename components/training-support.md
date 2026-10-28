---
title: Support-deck trainers and R4 gate
type: component
updated: 2026-10-29
sources: [rdf01-t8]
---
# Support-deck trainers and R4 gate

Offline tools that train the `support_*.pt` models from reviewed tags and measure them on held-out games (Hard Rule R4). Real training on collected data is human-gated; nothing here runs in the bot.

## Trainers (tools/)
All take `--data-dir` (default `<repo>/data`), `--tags`, `--exclude-games g1,g2`, `--epochs`, `--seed`; set torch threads from `TRAIN_THREADS`. Shared helpers (tag loading, atomic save, manifest) are in `support_train_common.py`.
- `train_support_type_cnn.py` → `support_type_cnn.pt` (10 `SUPPORT_CLASSES`). Gear tags (s1..s9, bomb, live, per-class caps as the gear trainer) contribute only labels that are support classes; support tags add all, incl. Resonance/Alignment. Uses `train_gear_type_cnn.train(..., n_out=)`, the only change to a gear trainer (default `n_out` keeps gear behaviour).
- `train_support_star.py` → `support_star_e<seed>.pt` (or `--out`): `PipNet(n_out=1)`, BCE, 50/50 resampled; positives = pip 7, negatives = other dice pip 1..6. Input is the `_hires` crop resized to 72 px (augment works at 72; no hue rotation since the star is yellow). Run seeds 1..3 for the ensemble.
- `train_support_pip.py` → `support_pip_pat_e<seed>.pt`: dot-pattern head (sets the gear trainer's module-global `tp.PATTERN = True`), type-blind, gear + support crops with pip 1..6 only (7 belongs to the star model).
- Every save is `.tmp` + `os.replace` (the bot hot-reloads). Each trainer merges `{model file: sorted game ids}` into `data/support_train_manifest.json`.

## Gate: `tools/support_gate.py --holdout g7,g8 [--tags ..] [--data-dir ..]`
- Refuses (prints `FAIL: holdout game <id> was used in training`, exit 1, writes nothing) if any holdout game appears in the manifest. Also exits 1 when the holdout has no checked crops.
- Evaluates only `chk`-true crops of the holdout games, through `perception.support` with the `auto` pip source; pip 7 is decided like `read_board_support` (star prob > 0.5 → 7, else min(pip, 6)) when star models exist.
- `metrics()` / `verdict()` are pure. Resonance and Alignment are per-class **recall**. Type PASS: overall, effect (`eff` flag), Resonance, Alignment all >= 0.90 and >= 50 crops each of Resonance and Alignment. Pip PASS: Res/Align pip accuracy overall and on effect crops, star recall and star precision all >= 0.90 and >= 30 pip-7 crops. Too few crops appends ` too few samples` and fails.
- Prints the two lines (`type gate: PASS (overall 0.953, ..., n=812)`, `pip gate: FAIL (Res/Align ..., stars=20)`, three decimals) then `written data/support_gate.json`: `created, holdout, type{..,pass}, pip{..,pass}, models{file: sha256}` for every `support.model_files()`. `support.gate_state()` reads it back (see [support perception](perception-support.md)).

## Gotchas
- The gate points `support._DATA` at `--data-dir`, so models, gate file and hashes all resolve there.
- A game trained on by any support model blocks it as holdout for good; retrain with `--exclude-games` first.

## Evidence
- commit `a453e82` — adds tools/support_gate.py, support_train_common.py, train_support_{type_cnn,star,pip}.py, the `n_out` parameter in tools/train_gear_type_cnn.py and tests/test_support_train_gate.py (metrics/verdict, manifest refusal, JSON round trip).
- commit `a453e82` (support_gate) — thresholds MIN_ACC/MIN_CLASS/MIN_STARS, line formats, chk filter, star decision rule.
- commit `a453e82` (train_support_star, train_support_pip) — BCE weighting, 72 px resize, no hue augmentation; PATTERN switch, pip 1..6 filter.
- [labelling tools](labelling-support.md) — produce the chk tags the gate reads.
