---
title: Support-deck milestone tracker and judge
type: component
updated: 2026-10-29
sources: [rdf01-t3]
---
# Support-deck milestone tracker and judge

`policy/milestones.py` (under `src/rdom`) turns confirmed scores and board counts into m1/m2/m3 milestone and 2000/3000/4000 crossing events; `tools/support_judge.py` decides the "4 of the last 5 games" acceptance from the round log. Both are pure and not yet wired into a play loop (the caller takes screenshots and writes the log). Sibling engines: [support-deck engine](policy-support.md), [power-up order](policy-power.md).

## Tracker (`MilestoneTracker`)
- `MILESTONES` = (name, score limit, min Resonance 7, min Alignment 7, min Bubbles): m1 (2000, 1, 1, 0), m2 (3000, 2, 1, 0), m3 (4000, 2, 3, 2). `CROSSINGS` = (2000, 3000, 4000).
- `on_board({res7, align7, bubbles})` resolves each milestone once, the first time its board condition holds. It is "reached" if the last confirmed score is below the limit, "late" if at or above it (late does not count). No confirmed score yet (`None`) counts as 0, so it is never late; the log prints `?` for the score.
- `on_score(score)` returns a crossing event the first time the score passes each of 2000/3000/4000 (several at once, in limit order), carrying the counts from the last `on_board` call, so a human can compare them with the screenshot.
- Event `log` strings are exact, e.g. `milestone m1 reached at score 1500 (Res7 1, Align7 1, Bubble 3)`, `milestone m2 late at score 3150 (...)`, `score crossed 2000 (...)`.
- `set_shot(event, path)` stores the screenshot path; `record()` returns `milestones`, `crossings` (keys `"2000"` etc.), `max_score`, `scores_confirmed` for the round record.

## Judge (`tools/support_judge.py`)
- `python tools/support_judge.py [--log data/support_rounds.jsonl] [--last 5]`; exit 0 pass, 1 fail, 2 cannot judge. `judge(records, last)` returns `(lines, exit_code)`; I/O only in `main()`.
- Eligible records: `mode == "play"`, `gates.type` and `gates.pip` true, `result == "game_over"`. The last N eligible in file order are judged. Other records are counted in a first line `제외 N판 (수집 모드 · 게이트 미통과 · 비정상 종료)`; mode `trial` or a false gate counts as gate-failed.
- A game passes when m1, m2 and m3 are all `reached` and `scores_confirmed > 0`; a game with no confirmed score gets ` · 점수 판독 실패` appended. Required count is `ceil(0.8 * last)` (4 of 5, 8 of 10).
- Unknown record keys (e.g. `power`, or `power: null`) are ignored, so the round-record schema can grow without judge changes. Unparseable JSONL lines are skipped.
- Output text is Korean and fixed by the spec; the last line is `판정: 통과|실패 — N판 중 K판 달성 (R판 필요)` or `판정 불가: 판정 대상 판이 N판뿐입니다 (L판 필요)`. stdout is reconfigured to UTF-8 for Windows consoles.

## Pitfalls
- `milestones.py` must not import `rdom.perception`, cv2 or torch, nor call `open`/`print`; tests enforce this (and no module-level side effects in the judge).
- A milestone resolves only once (`done`): if the condition first holds late, it never becomes "reached" later in the same game.

## Evidence
- commit `84141c4` — adds the milestones module (policy package, `MilestoneTracker`), the support_judge tool (`judge`) and their tests (test_support_milestones, test_support_judge); cited by commit because the files are not yet in the main checkout
- `C:/dev/_hub/tasks/rdf01-t3/task.json` — spec: acceptance AC1–AC13, exact log and Korean texts, eligibility and exit codes
