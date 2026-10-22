---
title: Recognition pitfalls (effects, glare, pips, empty cells)
type: lesson
updated: 2026-10-23
sources: [seed]
---
# Recognition pitfalls (effects, glare, pips, empty cells)

High offline accuracy did not hold on the live board: battle effects are colour overlays that hit the
same colours the classifier relies on. Act only on confident, repeated reads.

## Pitfalls
- **Selection bias**: the Predator-deck recognizer was trained only on crops a colour rule already
  labelled; the 2,659 `_unlabeled` effect crops were never seen, so 97.1% held-out was the "easy half".
  Per-crop split also leaked near-duplicate frames. Split by battle instead (Layer B, open).
- **Effects → systematic misreads**: Bubble glow → everything Light; opponent yellow buff → everything
  Predator (fixed by gray-world WB `_debuff_cast`); pink glitch → Switch; green buff arrows → Resonance;
  Predator stack digits break HOG.
- **Global corrections hurt partial effects**: board-wide cast/glare flags over-correct clean cells.
- **Majority vote does not filter persistent effects** (5 grabs in ~0.9 s all see the same glow) —
  hence the K-streak tracker with abstention.
- **Empty tile read as Predator**: range rings/effects add edges; switched to bright-face fraction
  (empty ≤ 0.06 vs die ≥ 0.58).
- **Pip errors**: Bubble pip-2 undercounted (purple dots weak on blue face, 14/15). In the gear bot a
  wrong pip read made merges fail → a merge whose cells did not change is banned until they change.
- **Single bad frame triggers actions**: a misread flipped a die to Adjust and fired the supporter
  (gear dry run 2026-10-07) → two identical consecutive reads required.
- **Tesseract misreads digits** (room code, HP) → template digit reader that returns None when unsure.

## Evidence
- `docs/07_RECOGNITION_REVIEW.md` — §1 diagnosis table, STATUS
- `CLAUDE_CODE_TODO.md` — "빈칸 인식 강건화", "눈금(pip) 인식" (#13 Bubble), Layer A–C items
- `docs/02_STRATEGY.md` — "라이브 인식 보정" (yellow buff)
- `src/rdom/perception/board.py` — `_bright_frac`, `_debuff_cast`, `board_glare`
- `tools/gear_bot.py` — docstring (Adjust misread, merge ban)
- `src/rdom/perception/digits.py` — docstring
