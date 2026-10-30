---
title: Score reader and generic digit-template kinds
type: component
updated: 2026-10-30
sources: [rdf01-t4, rdT01, rdf02-t1, rdf02-t2, rdf02-i2, rdf03-t3]
---
# Score reader and generic digit-template kinds

`perception/score.py` reads the top-centre in-battle score exact-or-None with the template digit reader. `ScoreTracker` confirms a value after two identical consecutive reads. `tools/build_digit_templates.py` can now build `digits_<kind>.npz` for any kind name. `SCORE_BOX` is measured and `assets/templates/digits_score.npz` is committed (rdf02-t1), so `read_score` reads real H1 battle frames; `tools/check_support_assets.py` re-checks it against `data/`.

## read_score
- `SCORE_BOX = (0.36, 0.083, 0.64, 0.126)` as `(u0, v0, u1, v1)` in content-normalised coordinates, measured on 1244x2224 H1 frames (names in the code comment). The yellow 4-digit fill spans u 0.396-0.599, v 0.088-0.122; the box leaves room for a 5th digit and stops above the '처치한 몬스터' label (v ~0.127), which the 'field full' banner can overlap.
- A 2-D grey frame is accepted (no colour conversion) and gives None rather than a cv2 error. There is no thousands-separator filter; a synthetic '2,000' returns 2000 or None, never another number (tests/test_support_score.py).
- The crop uses true 9:16 content width `round(h*9/16)` (same as `gear._content_w`), converts RGB to grey and calls `digits.read_number(gray, "score")`.
- Returns None when `SCORE_BOX` is None, the crop is empty, the reader refuses, or `digits_score.npz` is missing (`OSError` from the template load is caught).
- Tests need no `data/`: they render digits with `cv2.putText`, build templates into `tmp_path`, then monkeypatch `digits._TPL`, clear `digits._cache` and set `SCORE_BOX`.

## ScoreTracker
- `update(read)` returns the score only on the read that confirms it (equal to the previous non-None read), else None; `.value` holds the last confirmed score.
- A None read neither confirms nor resets the pending value, so `1500, None, 1500` still confirms. A different value (1600) must be read twice.
- Plausibility (rdT01): a read below 0, above `MAX_SCORE` (99999) or lower than the last confirmed `.value` returns None like a failed read: it does not confirm and does not reset the pending value. Assumes one tracker per battle and an in-battle score that only rises (4000 then 100 keeps 4000; 4000 then 4100, 4100 confirms 4100).

## Asset check (`tools/check_support_assets.py`)
- `python tools/check_support_assets.py [--data-dir D]` prints `score: n= correct= none= wrong=` over `D/digits/score/<value>_*.png` crops and `score lobby: none=k/n` over non-battle frames in `D/support_frames/manual`. Exit 1 only on an exception; missing dirs give n=0.
- Crops are cut with `SCORE_BOX`, so `check_score` pastes each crop back at the box position in a blank 2224-high frame before calling `read_score`. Unreadable files and names without an integer prefix are skipped, not counted.
- Last run on `C:/dev/rdom/data` (2026-10-29): `score: n=42 correct=38 none=4 wrong=0`, `score lobby: none=1/1`. `wrong` must stay 0 (exact-or-None reader).
- rdf02-t2 added `--out-dir` (default `<data-dir>/support_frames/_check` since rdf02-i2, resolved after parsing because it depends on `--data-dir`; it was a temp folder before, which left the folder named in spec R4 and the runbook empty) and three more lines: `deck bar: support t/n gear-false g/m`, `deck bar excluded: k (names, max 10 then ...)`, `power cards: k/n`, `lv box: drew n overlays to <dir>`. Support frames are `sup*/<t>.png`; ones with the power panel open ("panel") or no battle ("bar hidden") are excluded and listed, `panel_*.png` frames feed power cards and the LV_BOX overlays. A power-cards frame counts only if Growth, Alignment and Resonance sit on three different buttons. H1 run: `deck bar: support 181/181 gear-false 5/5`, `excluded: 0`, `power cards: 5/5`, `lv box: drew 5`. Templates and LV_BOX: [perception-support.md](perception-support.md).
- Tests (tests/test_support_assets_score.py, tests/test_support_assets_ui.py) use synthetic digits in `tmp_path` and assert the committed npz has `T` of shape (10, GH, GW).

## Battle SP and summon cost (`perception/sp.py`, rdf03-t3)
- `read_sp(frame)` (0..9_999_999) reads the white digits on the dark pill above 소환; `read_summon_cost(frame)` (1..99_999) reads the digits on the 소환 button. Same recipe as `read_score`: true 9:16 width, grey, `digits.read_number(gray, kind)` with kind `sp` / `cost`; None on missing npz, empty crop, refusal, out of range, 2-D grey, tiny or odd inputs. `read_crop(gray, kind)` is the shared cut-crop reader.
- `SP_BOX = (0.446, 0.790, 0.600, 0.813)`, `COST_BOX = (0.4745, 0.876, 0.575, 0.897)`. The 'Ø' icon must stay outside: it is fixed for SP (digits start u 0.451) but moves with the digit count on the button, so for a 2-digit cost (10..90, first summons only) a sliver of it is inside and the read is None by design (the 4 none of the check run).
- Templates `digits_sp.npz` / `digits_cost.npz` come from `data/digits/sp` / `data/digits/cost` via `build_digit_templates.py sp cost`; all ten digits had samples, so no room-template fallback. A cyan '+N' kill popup over the SP digits must read None, never a wrong number.
- `check_support_assets.py` prints two more lines after the existing ones: `sp: n= correct= none= wrong=` and `summon cost: n= correct= none= wrong=`. Crops in those folders cut with other boxes by earlier tries are skipped (`_fits_box`: pixel size must match the box within 1 px), otherwise pasting them back would stretch the digits. Run 2026-10-30: `sp: n=34 correct=33 none=1 wrong=0`, `summon cost: n=56 correct=52 none=4 wrong=0`.
- `tools/support_dryrun.py` adds `sp: <n|None>` and `summon cost: <n|None>` after the score line. Not yet used by the bot loop (rdf03-t5/t6).

## Building templates for a kind
- `build_kind(kind, src_dir, out, thr, fallback)` reads `<src_dir>/*.png`; the value is the filename part before the first `_` (checked by eye). Non-digit names and unreadable images are skipped.
- Digits with no sample take `fallback`. The CLI passes the room templates, which share the game font.
- `python tools/build_digit_templates.py score powerlv` builds those kinds from `data/digits/<kind>/`; with no arguments the old room + hp flow runs unchanged. `powerlv` is intended for the power-card level digits.
- `build()` gained an `out` directory parameter. The room/hp code moved into `main()`, so importing the module no longer rewrites `assets/templates` (tests rely on this).

## Evidence
- `src/rdom/perception/digits.py` — `_TPL`/`_cache` (what the tests patch) and `read_number` (template load raises `OSError` when the npz is missing).
- `tools/build_digit_templates.py` — `build(out=)`, `build_kind`, the `__main__` dispatch and `main()`.
- commit `2dd0464` (branch task/rdT01) — `MAX_SCORE` and the implausible-read guard in `ScoreTracker.update`; tests in tests/test_support_score.py.
- `src/rdom/perception/score.py` — `SCORE_BOX` value and measurement comment; grey-frame handling in `read_score`.
- commit `9273516` (branch task/rdf02-t1, not yet merged into this checkout when written) — adds tools/check_support_assets.py (`check_score`, `_frame_for_crop`, `check_score_lobby`, docstring with the run on `data/`), tests/test_support_assets_score.py, assets/templates/digits_score.npz, and the box/separator/degenerate-input tests in tests/test_support_score.py.
- commit `ee3d48d` (branch task/rdf02-t2, not yet merged into this checkout when written) — tools/check_support_assets.py: check_deck_bar, check_power_cards, draw_lv_boxes, --out-dir and the docstring with the H1 run; tests/test_support_assets_ui.py.
- commit `ad02bed` (branch task/rdf02-i2) — tools/check_support_assets.py: `--out-dir` default None resolved in `main()` to `<data-dir>/support_frames/_check`; tests/test_support_assets_score.py `test_main_default_out_dir_is_support_frames_check`.
- commit `0313471` (branch task/rdf03-t3) — src/rdom/perception/sp.py (boxes, ranges, icon/popup comments), tools/check_support_assets.py (`_check_digits`, `_fits_box`, docstring run), tools/support_dryrun.py, assets/templates/digits_sp.npz and digits_cost.npz, tests/test_support_sp.py.
- commit `29b2651` (branch task/rdf01-t4, not yet merged into this checkout when written) — adds perception/score.py (`SCORE_BOX`, `read_score` guards, `ScoreTracker.update` None handling) and tests/test_support_score.py (synthetic-glyph tests for reader, tracker and build helper).
