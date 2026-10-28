---
title: Score reader and generic digit-template kinds
type: component
updated: 2026-10-29
sources: [rdf01-t4]
---
# Score reader and generic digit-template kinds

`perception/score.py` reads the top-centre in-battle score exact-or-None with the template digit reader. `ScoreTracker` confirms a value after two identical consecutive reads. `tools/build_digit_templates.py` can now build `digits_<kind>.npz` for any kind name. The real `SCORE_BOX` and `digits_score.npz` do not exist yet, so `read_score` returns None in production.

## read_score
- `SCORE_BOX = None` until measured on real frames (a later task). It is `(u0, v0, u1, v1)` in content-normalised coordinates.
- The crop uses true 9:16 content width `round(h*9/16)` (same as `gear._content_w`), converts RGB to grey and calls `digits.read_number(gray, "score")`.
- Returns None when `SCORE_BOX` is None, the crop is empty, the reader refuses, or `digits_score.npz` is missing (`OSError` from the template load is caught).
- Tests need no `data/`: they render digits with `cv2.putText`, build templates into `tmp_path`, then monkeypatch `digits._TPL`, clear `digits._cache` and set `SCORE_BOX`.

## ScoreTracker
- `update(read)` returns the score only on the read that confirms it (equal to the previous non-None read), else None; `.value` holds the last confirmed score.
- A None read neither confirms nor resets the pending value, so `1500, None, 1500` still confirms. A different value (1600) must be read twice.

## Building templates for a kind
- `build_kind(kind, src_dir, out, thr, fallback)` reads `<src_dir>/*.png`; the value is the filename part before the first `_` (checked by eye). Non-digit names and unreadable images are skipped.
- Digits with no sample take `fallback`. The CLI passes the room templates, which share the game font.
- `python tools/build_digit_templates.py score powerlv` builds those kinds from `data/digits/<kind>/`; with no arguments the old room + hp flow runs unchanged. `powerlv` is intended for the power-card level digits.
- `build()` gained an `out` directory parameter. The room/hp code moved into `main()`, so importing the module no longer rewrites `assets/templates` (tests rely on this).

## Evidence
- `src/rdom/perception/digits.py` — `_TPL`/`_cache` (what the tests patch) and `read_number` (template load raises `OSError` when the npz is missing).
- `tools/build_digit_templates.py` — `build(out=)`, `build_kind`, the `__main__` dispatch and `main()`.
- commit `29b2651` (branch task/rdf01-t4, not yet merged into this checkout when written) — adds perception/score.py (`SCORE_BOX`, `read_score` guards, `ScoreTracker.update` None handling) and tests/test_support_score.py (synthetic-glyph tests for reader, tracker and build helper).
