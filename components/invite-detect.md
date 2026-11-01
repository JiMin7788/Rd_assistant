---
title: Invite popup and joined-room detection
type: component
updated: 2026-11-01
sources: [rdf04-t3, rdT05]
---
# Invite popup and joined-room detection

`rdom.perception.invite` finds the 게임 초대 popup, reads the inviter name from its banner and tells when the bot is inside a 협동 같이하기 room. Pure functions on a content frame; nothing calls them yet (not wired into a bot loop).

## Entry points
- `invite_popup(f)` returns `{'accept_uv', 'close_uv'}` or None. It needs both `invite_title.png` (TITLE_BOX) and `invite_accept.png` (ACCEPT_BOX) at >= 0.80. `accept_uv` is the matched button centre, `close_uv` is the fixed X `CLOSE_UV = (0.867, 0.171)`.
- `joined_room(f)` is True when `board.has_modal_x(f)` holds and `room_title.png` (ROOM_TITLE_BOX) scores >= 0.80; the same check serves host and joiner view.
- `invite_name_matches(f, host)` returns `(matched, name_read)` and is what the joiner uses. It OCRs NAME_BOX (`friend_coop._ocr_data`) at every cut in `NAME_THRESHOLDS = (150, 130, 170, 100, 190, 210)` and keeps Hangul syllables only per row (the banner artwork makes Tesseract emit stray punctuation and digits). It is True when ANY row at ANY threshold passes `name_matches`, and stops at the first match. `name_read` is the matching row, else the longest Hangul row seen ('' if none). Reason: a single cut (150) read nothing on live GPG frames of 2026-11-01 (1252x2232); each cut reads the name on some frames and not others, and a junk row must not hide a good one.
- `invite_name(f)` is for logging only: the longest Hangul row over all thresholds, '' if unreadable. Do not use it for the accept decision.
- `name_matches(text, host)` accepts equal strings (spaces removed) or `friend_coop._name_cover >= NAME_COVER_MIN` (0.8). A false accept would put the bot in a stranger's room, so a weak cover is rejected.
- `scores(f)` returns the raw three template scores for threshold work.

## Detection method
Template matching only (`gear._best`, multi-scale, TM_CCOEFF_NORMED); no hue bands (docs/07). Templates `assets/templates/invite_title.png`, `invite_accept.png`, `room_title.png` were cut from the GPG fixtures; the LD frames, about 9 % narrower, match at scale 0.9.

## Measured scores and why 0.80
| template | positives | highest negative |
|---|---|---|
| invite_title | GPG 1.000, LD 0.943 | 0.608 |
| invite_accept | GPG 1.000, LD 0.974 | 0.440 |
| room_title | GPG 1.000, LD host rooms 0.936 | 0.565 |

Negatives were the six rdF04 fixtures against the templates they are not, plus 63 frames read by absolute path from the main checkout's `data/` (20 support result screens, 43 battle/panel frames). There are no LD lobby frames in `data/`, so lobby negatives are only the fixtures' own. All three thresholds sit mid-gap at 0.80.

## Pitfalls
- On LD the popup's yellow 초대 수락 button reads `start_ready` True ([profiles-ld](profiles-ld.md)); this module does not change that detector, it only offers `invite_popup` as the separate check.
- The lower 협동 같이하기 text of the popup starts at v 0.26, so ROOM_TITLE_BOX ends at v 0.25 to keep popups out (popup scores 0.443 GPG, 0.459 LD).
- Name OCR is unverified on live LD frames; only the fixtures were used. On GPG, six live popup frames (`tests/fixtures/rdf04/gpg_popup_2257*.png`, `_2258*.png`) plus `gpg_invite_popup` all match 대변먹는자, and none matches 배속봇, 웅로어 or 홍길동 (tests/test_invite.py). The LD fixture still reads its own name 배속봇 and does not match the GPG host.
- Cost: up to 6 OCR passes per popup frame when nothing matches (a decline path), one pass set per read in the joiner.

## Evidence
- commit `829080e` (branch task/rdf04-t3, not yet merged into this checkout, so paths are not lint-checked) — adds src/rdom/perception/invite.py (functions, boxes, thresholds, docstring with the measured scores and negative set), the three templates in assets/templates/, and tests/test_invite.py.
- commit `4141695` (branch task/rdT05, not yet merged into this checkout, so paths are not lint-checked) — src/rdom/perception/invite.py adds NAME_THRESHOLDS, `_name_rows`, `invite_name_matches` and the longest-row `invite_name`; tests/test_invite.py runs the six live GPG fixtures and the other-host declines.
