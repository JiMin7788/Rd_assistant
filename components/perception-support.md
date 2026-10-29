---
title: Support-deck perception
type: component
updated: 2026-10-29
sources: [rdf01-t5, rdf02-t2, rdf02-t3, rdf02-r2-s12]
---
# Support-deck perception

`perception/support.py` reads the support deck's board with its own model files (`data/support_*.pt`), reports the R4 gate state, detects the deck bar, finds the three power cards and reads a card level. It reuses gear helpers and changes nothing in gear. Not yet used by the bot loop; real models, templates and `LV_BOX` come from later tasks.

## Why a separate model
`PipNet` embeds `len(gear.TYPES)` types, so growing gear's TYPES would break loading the gear pip weights. The support type net is `gear._pipnet_cls()(n_out=len(SUPPORT_CLASSES))`. Pip nets are built with `n_out=7`, star nets with `n_out=1`.

## Board (read_board_support)
- Returns 15 dicts `{cell, type, variant, pip, conf}`, cells 1..15. `variant` equals `type`. It is `read_cells_support(frame, range(1, 16), pip_source)`.
- `read_cells_support(frame, cells, pip_source="auto")` reads only the given cells (1..15) and returns raw dicts in the given order; each equals the same cell's entry in `read_board_support` (the star check uses the real cell number for `hires_cell`, not the batch position). Empty list gives `[]`. Any cell outside 1..15 (0, negative, 16+) raises `ValueError` before anything is read; without that check cell 0 or a negative number indexed the crop list from the end and returned another cell's read under the wrong label.
- `READ_CONF_MIN = 0.90`: a read is unreadable when its type is junk or `conf < READ_CONF_MIN`. `read_cells_support` does not apply it; callers do. Measured with `tools/support_conf_report.py --holdout sup20261029_152652 --tags sup1`: at conf >= 0.90 kept 1003/1008 (99.5%), accuracy of kept 0.997, 3 wrong kept, 1 wrong dropped; 0.90 is the largest threshold keeping >= 95% of the checked crops. The tool prints one line per T in 0.50..0.95 and refuses a holdout game listed in the train manifest; it loads the type model from `--data-dir`.
- Without `support_type_cnn.pt` every cell is `junk`, pip 0, conf 0.
- A CNN `Bomb` becomes `junk` unless `gear.is_bomb(crop)` (then `Bomb`, conf 1.0), as in gear's `predict_types`. Pip is 0 for empty/junk/Crystal/Bomb.
- Pip source: `"auto"` uses `support_pip_pat_e1..e3.pt` when all three exist, else the gear ensemble (`gear.PIP_ENSEMBLE`), else the single `gear_pip_pat.pt`, else pip 0. `"gear"` (trial mode) always uses the gear files and loads no support pip or star file.
- Star (pip 7), `auto` only and only when all three `support_star_e*.pt` exist: mean sigmoid over `hires_cell(frame, cell, 128)` resized to 64; p > 0.5 gives 7, otherwise a 7 from the ensemble becomes 6. Without star files the ensemble pip is returned as is.

## Gate (Hard Rule R4)
`gate_state()` returns `{"type": bool, "pip": bool}` from `data/support_gate.json` (`models` = filename to sha256, `type.pass`, `pip.pass`). Both are False when the file is missing/unparseable, a listed file is missing or its sha256 differs, or a present support model (type/pip/star) is not listed. The last rule is stricter than the task spec: a retrained model dropped in unlisted is not live until re-gated.

## Deck, cards, level
- `force_deck()` returns `force` from `config/deck.toml` if it is a string, else `""`.
- `detect_support_deck` matches `assets/templates/deck_support.png` in box `(0.55, 0.93, 0.92, 0.99)` with `gear._best` (multi-scale), score >= 0.70; False if the template is missing.
- `power_cards` searches band `(0, 0.78, 1, 0.96)` for each card template (Alignment has two looks, `_a`/`_b`, best score wins), score >= 0.70, and maps the card to the `gear.power_buttons` centre nearest in u with |du| < 0.06 (slot order is the user's choice, so not deck order). Result has exactly Growth/Alignment/Resonance, None when not found. Two cards on one button: the higher score keeps it.
- `card_level(frame, button)`: `LV_BOX = (0.0160, -0.0414, 0.0448, -0.0261)` (offsets from the button centre, measured on the five H1 panels in rdf02-t2; starts right of the 'Lv.' dot because a dot in the box makes `digits.glyphs` return None, ends at +56 px for a second digit); crop to grey then `digits.read_number(g, "powerlv")`; None if the box is None, the crop is empty, `digits_powerlv.npz` is missing, or the value is outside 1..30.
- `reload_if_changed()` drops cached nets whose mtime changed (support and gear pip files) and returns the names; the first call reports every file once.

## Templates (rdf02-t2)
`assets/templates/` now holds `deck_support.png` and the card icons `ui_power_res_card.png`, `ui_power_align_card_a.png`, `ui_power_growth_card.png` (icon only, below the dice-count badge, above 'Lv.N'). There is no `ui_power_align_card_b.png`: only one Alignment look is on the panel, the missing `_b` is simply skipped. Card identity was fixed by matching the panel icon to board dice whose labels come from `support_type_cnn`, not by slot order (details in the `CARD_TEMPLATES` comment). `tools/check_support_assets.py` on the H1 data: deck bar support 181/181, gear-false 5/5, power cards 5/5 (see [score page](perception-score.md) for the tool).

## Tests
`tests/test_support_perception.py` needs no `data/`: fake nets via monkeypatched `_load_net`, synthetic frames, templates and data dirs in `tmp_path` (patch `support._DATA`/`_TPL`/`DECK_FILE`, clear `support._models`).

## Evidence
- commit `a2c2b9c` (branch task/rdf01-t5, not yet merged into this checkout when written) — adds perception/support.py (all behaviour above: `_pip_files`, `read_board_support`, `gate_state`, `power_cards`, `card_level`, `reload_if_changed`) and tests/test_support_perception.py (synthetic tests for pip source, star, gate, cards); touches no gear file.
- commit `ee3d48d` (branch task/rdf02-t2, not yet merged into this checkout when written) — support.py `CARD_TEMPLATES` comment (card identity evidence) and `LV_BOX` value/comment; the three card PNGs and deck_support.png under assets/templates; tests/test_support_assets_ui.py (templates exist, LV_BOX is four floats, check-tool lines on synthetic frames).
- commit `bf6ad6c` (branch task/rdf02-t3, not yet merged into this checkout when written) — support.py `read_cells_support` and the `READ_CONF_MIN` comment with the measured numbers; tools/support_conf_report.py (`report`, `main`); tests/test_support_conf_report.py (cells equal board entries, per-cell star, threshold edges, holdout refusal).
- commit `b294b48` (branch task/rdf02-r2-s12) — support.py `read_cells_support` range check (`ValueError` for cells outside 1..15, AI-NOTE explains the negative-index cause); tests/test_support_conf_report.py `test_read_cells_support_rejects_cells_outside_1_15` (0, -1, 16, mixed list raise; valid list unchanged).
- `src/rdom/perception/gear.py` — `_pipnet_cls`, `PIP_ENSEMBLE`, `is_bomb`, `power_buttons`, `_best` reused here.
