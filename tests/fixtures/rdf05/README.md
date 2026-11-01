# rdF05 fixtures (minigame gauge) — cut by `tools/rdf05_fixtures.py`

Source: `C:/dev/_hub/features/minigame/rec/gpg_20261102_003916.mp4` (GPG, 60 fps, 622x1116 content, read by
absolute path, never copied). Time t = frame / 60. Hard Rule R5: no status bar (every crop starts at v 0.40),
and every ranking-list frame is mosaicked (12 px blocks) so no nickname or account name is readable.

Stored crops are WebP of the 622x1116 content frame; the tests pad them back with black (positives hold
v 0.40-0.86, negatives v 0.40-0.70 = the bar search strip). Total < 3 MB (tested).

## Gauges (frame ranges, from scanning the recording)
| gauge | frames | t (s) |
|---|---|---|
| 1 | 3380-3658 | 56.33-60.97 (bar zooms in over the first 3 frames, 56.33-56.37) |
| 2 | 3659-3783 | 60.98-63.05 |
| 3 | 4523-4939 | 75.38-82.32 |
| 4 | 4940-5086 | 82.33-84.77 |
| 5 | 5754-5968 | 95.90-99.47 |
| 6 | 5969-6193 | 99.48-103.22 |
| 7 | 7000-7206 | 116.67-120.10 |
| 8 | 7207-7421 | 120.12-123.68 |

## Files
- `frames/g<gauge>_<frame>.webp` — 80 labelled gauge frames (source time in `labels.json` `t`, 6-11 per gauge, evenly spaced after the zoom-in).
- `labels.json` — per frame: tip u, tip_v, yellow edges and all six segment edges (`seg`), bar span, bar v, button box. Sub-pixel channel crossings, checked on 4x montages with the label lines drawn.
- `full/f_<frame>.webp` — one full 622x1116 frame per gauge: 3519 (58.65 s), 3721 (62.02 s), 4731 (78.85 s), 5013 (83.55 s), 5861 (97.68 s), 6081 (101.35 s), 7103 (118.38 s), 7314 (121.90 s).
- `zoom/z_03380..03383.webp` — the first four frames of gauge 1 (56.33-56.38 s): the zoom-in bar that is not the settled bar.
- `neg/n_<frame>.webp` + `negatives.json` — 180 non-gauge frames, evenly spaced over the recording outside each gauge (-0.5 s .. +1.5 s): 85 before 90 s (tuning), 95 from 90 s (held out). Screens (windows read off the 2 s contact sheet; `test_negatives_have_no_gauge` asserts at least one frame in each): event screen 군밀 대청소 (4.5-6.3 s and 38-52 s), ranking list (7-37 s, `mosaic: true`), loading/black (52-54 s), reel (64.5-67.5 s), flight (68-73 s), distance result (73.5-75 s). The start screen 대청소 시작, reel, flight, result and fade repeat before and after every later run and are sampled there too. Only the bar search strip is stored, so the green 대청소 시작 button (below it) is not in the negatives.
- `traces.json` — per gauge: `series` of [t, tip_u] from `read_gauge` (DEFAULT_PARAMS) on every frame where the gauge was read (t = frame / 60), `yellow` interval (median over settled frames), `stop_frame` (first frame of the final tip position, the user's release).
