---
title: Minigame gauge recognizer (군밀 대청소)
type: component
updated: 2026-11-02
sources: [rdf05-t1]
---
# Minigame gauge recognizer (군밀 대청소)

`perception/minigame.py` reads the stop-the-triangle bar (blue-purple-yellow-purple-blue segments, a
red triangle under it, a green 멈춰 button below) from one RGB content frame. Pure functions, no input, not wired
into any loop yet. Proven only on half-size GPG video.

## Entry points
- `read_gauge(frame, params=DEFAULT_PARAMS)` -> `GaugeRead(bar, v, segments, yellow, tip_u, button)` or `None`.
  Needs the bar, the triangle and the button together; any one missing gives `None`.
- `read_bar` is the bar stage alone (negative tests call it on strips that stop above the button).
- `read_tip(band, band_box)` reads only the triangle tip u on a crop of the content.
- `zone_at(read, u)` -> yellow / purple / blue / outside (edges inclusive, yellow beats purple beats blue).
- `same_gauge(a, b, tol=0.004)` compares bar span and all segment edges (tells a new bar from the same one).
- `fit_params(frames, labels)` refits every colour prototype, tolerance and size range from labelled frames.

## How it works
- A frame is resized to `CANON_W` = 622 px wide first, so half-size video frames and full-size live frames share
  one path. All outputs are content-normalised (u, v). The bar is searched in v 0.40-0.70 (no fixed coordinates).
- No hue bands (docs/07): each pixel goes to the nearest of four RGB prototypes (blue, purple, yellow, dark bar)
  or to none beyond that prototype's tolerance. A row is a gauge row when its solid runs show
  blue-purple-yellow-purple-blue with gaps <= `GAP_PX` (5); >= `MIN_ROWS` (3) rows must agree.
- Segment edges are midpoints of the anti-aliased gaps between runs. The bar span is the widest span any agreeing
  row shows, because the triangle hides dark bar next to it on some rows.
- Look-alikes rejected by order + dark bar + triangle + button: multiplier reel tiles and the result texts above
  the bar (나이스 cyan-blue, 완벽해 yellow, 쿨 purple).
- Where the result text covers the bar the reader returns `None`; the loop only meets that after the stop.

## Parameters
`DEFAULT_PARAMS` is the fit on all 8 recorded gauges (80 labelled frames), pasted as literals;
`test_default_params_equal_full_fit` fails if they drift. After changing the detector or the fixtures, re-run
`fit_params` and paste the new literals.

## Results (held out, leave-one-gauge-out, 8 folds)
- 80/80 labelled frames within 0.005 u, worst error 0.0022 u; 8/8 gauges detected.
- 180 negatives (33 mosaicked ranking lists), 95 of them held out (recording time >= 90 s): 0 false gauges
  with every fold's params and with `DEFAULT_PARAMS`.
- The first four frames of gauge 1 are the zoom-in bar, not the settled bar (`zoom/` fixtures; tested).

## Fixtures (tests/fixtures/rdf05, cut by tools/rdf05_fixtures.py)
- Source recording `C:/dev/_hub/features/minigame/rec/gpg_20261102_003916.mp4`, read in place, never copied.
- Stored crops are WebP starting at v 0.40 (no status bar, Hard Rule R5); ranking-list negatives are mosaicked
  (12 px blocks) so no nickname is readable. Total < 3 MB (tested). The tests pad crops back with black.
- `labels.json` comes from sub-pixel channel crossings on the original frames; `traces.json` holds per-gauge
  `[t, tip_u]` series, the yellow interval and `stop_frame` (the user's release). The layout of every file is in
  the fixtures README.
- `.scratch/` is git-ignored for throwaway checks.

## Not yet proven
Full-scale GPG (1244x2224) and LD (1122x1994) frames are unproven until the human dry runs (H5).

## Evidence
- commit 64b3da2 (task/rdf05-t1, merged after this page was written, so the files are not yet in the main checkout) adds all of the following:
  - src/rdom/perception/minigame.py — entry points, constants, pipeline, DEFAULT_PARAMS and the held-out table in the module docstring.
  - tests/test_minigame_perception.py — leave-one-gauge-out, params-equal-full-fit, negatives, zoom-in, zone_at, same_gauge, size-budget tests.
  - tests/fixtures/rdf05/README.md — source video, gauge frame ranges, file layout, mosaic/R5 rules.
  - tools/rdf05_fixtures.py — how crops, labels, negatives and traces are produced; tests/fixtures/rdf05/labels.json holds the 80 labelled frames.
  - .gitignore — adds a git-ignore entry for the throwaway scratch directory.
