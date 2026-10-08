# 07 — M1 Recognition Review & Redesign Proposal (2026-09-17)

Scope: `src/rdom/perception/{board,features}.py`, `tools/train_recognizer.py`,
`tools/bot_live.py` (read/lock/verify loop), crop data under `data/crops`.
Trigger: recognition keeps breaking under battle effects (glow wash, colour-cast
buffs, glitch/pink overlays, Predator digits, buff arrows) whose colours overlap
the dice's own identity colours.

---

## STATUS — Layer A IMPLEMENTED (2026-09-17)

**Done** (no retraining, as recommended):
- `classify_type` now returns a real confidence from `predict_proba`: `p_max` folded
  with the top-2 margin, dropping to `LOW_CONF (0.45)` when `p1 < 0.60` or margin `<
  0.25`. `read_board` carries a per-cell `conf`. (board.py)
- `perception/tracker.py` — `CellTracker`: per-cell belief with abstention (obs conf
  `< 0.50` ignored), K-streak change rule (K=3 normal, 8 Predator / 5 Light for a
  correct fixed cell, 1 for empty→die and just-swapped cells, 2 for →Bomb), and
  action-aware resets (switch swaps beliefs + accepts next frame; merge/destroy frees
  the source). `belief_board()` + `uncertain()` feed the planner.
- `bot_live.py` work loop rewritten on the tracker: deleted `locked`/`wrongrun`, the
  double-read "switch unconfirmed" block, and the ">11 same type" guard. Uncertain
  cells are passed as `locked` so the planner never touches a die it isn't sure of.
- Gate tests `tests/test_tracker.py` (10) pass: a glow/effect burst never changes a
  settled belief; a correct Predator survives 7 confident wrong reads and flips only
  on the 8th; a swap is reflected immediately and self-repairs in one frame.
- Live smoke test (real board frame): predators read 0.80-0.98; the 4 effect-covered
  cells abstained (conf 0.45) → held out of planning instead of misread.

**Deliberate simplification vs the proposal:** the per-cell effect detector (A.2:
explicit `wash/cast/pinkglitch/dark`) and per-cell white balance were folded into
model confidence — an effect that confuses the die also lowers `p_max`/margin, so
abstention catches it without hand-tuned thresholds (verified on the smoke frame).
Per-cell white balance and the tile-corner reference remain a future refinement.

**Not started:** Layer B (temporal label propagation, split-by-battle metric, drop
CAP) and Layer C (CNN / overlay-invariant features, two-stage head, pip-2). These
need recorded sessions with frames+action logs — see below.

---

---

## 1. Diagnosis — why 97.1% held-out does not translate to the live board

### 1.1 The training set is filtered by the very rule that fails (selection bias)
`_collect_crops()` labels a crop with `strict_label()` — a colour rule — or drops it into
`_unlabeled`. The model is then trained ONLY on crops the colour rule was already sure
about. Consequences:

- The 5 labelled classes contain the *easy* distribution (clean colours). The 2,659
  `_unlabeled` crops are exactly the effect frames the bot fails on. The model has never
  seen that distribution, so the reported 97.1% is accuracy on the easy half.
- Any error in `strict_label` becomes a label error the model faithfully learns
  (e.g. a glowed Resonance that passed `bw >= 0.65 and darkblue < 0.03` is stored as Light).
- `train_test_split` on individual crops from consecutive frames leaks near-duplicates
  between train and test (the 8×8/32 dedupe hash only drops *identical* boards). The
  metric is optimistic even on the easy distribution.

### 1.2 The features are the thing the effects destroy
`_color_features()` is 21 hand-set HSV hue-band fractions (tan 8–32, green 40–95, …).
Every effect on the board is a colour overlay, so it moves pixels across those bands:

| Effect (seen in crops)                   | What it does to the features                       | Typical misread            |
|------------------------------------------|----------------------------------------------------|----------------------------|
| Bubble glow (`Dice_Glow`, whole board)   | S→0, V→255 on the face; only frame ring survives   | everything → Light         |
| Yellow buff (opponent)                   | R,G ≫ B → all hues drift into the tan band         | everything → Predator      |
| Red/orange attack swirl on Resonance     | adds hue 0–20 + 170–180 → tan/pink bands           | Resonance → Predator/Switch|
| Pink/magenta glitch (RGB-split frame)    | adds hue 148–172 → pink band                       | anything → Switch          |
| Green buff arrows `^^^`                  | adds hue 40–95 to the face                         | Predator/Light → Resonance |
| Predator stack digits (`644`, `1166`…)   | dark strokes vary per frame → HOG unstable         | Predator → Light/empty     |
| Purple pip clusters (pip ≥ 2)            | purple/darkblue fraction jumps                     | Light → Bubble             |

The HOG branch does not rescue this: it is computed on a per-crop standardized grey image,
so under glow (`std→0`) it amplifies noise, and the Predator digits give every Predator a
different "shape".

### 1.3 `_debuff_cast` is board-global, effects are local
The yellow-cast correction scales the *whole frame* from the *board-mean* colour. A partial
cast (3 cells lit, 12 not) is under-corrected on the lit cells and over-corrected (blue-shifted)
on the clean cells — the latter pushes clean Light toward Bubble. Same for `board_glare`:
a single `glary` flag flips all 15 cells into border-mode even when only some are washed.

### 1.4 The classifier can never say "I don't know"
`classify_type` returns `(label, 1.0)` from `model.predict()`; `predict_proba` is unused.
Everything downstream (locks, 8-frame streaks, double-read confirmation, wobble skips) is
compensating for a missing confidence signal. Those guards work for the 8 FIXED cells only;
the 7 n-cells and the Switch have no protection, and `read_board_stable(n=2)` cannot break a
tie (Counter returns the first-inserted → it is just "first frame wins").

### 1.5 The temporal model is too short
`read_board_stable` votes 5 grabs over ~0.9 s. The glow, buff and popup effects last several
seconds, so all 5 votes see the same effect and agree on the same wrong answer. Majority vote
filters flicker; it does not filter *persistent* effects.

### 1.6 The strongest prior is not used
Own-field dice do not change unless: the bot summons (fills exactly one empty cell), the bot
swaps/merges/destroys, a field effect transforms a cell, or a bomb appears. The board is a
slowly changing state, but every frame is classified from scratch as if it were independent.

---

## 2. Proposed solution — three layers, in order of cost

### Layer A — Belief tracker + abstention (no retraining, ~1 day)  ← do first
Turn perception from "classify each frame" into "update a per-cell belief".

1. **Confidence out of the model.** In `classify_type` use `predict_proba`; return
   `(label, p_max)`. If `p_max < 0.6` or top-2 margin `< 0.25` → `("unknown", p)`.
2. **Per-cell effect detector** (replace the global `glary`/`_debuff_cast` flags):
   for each crop compute `wash = white_frac`, `cast = min(R,G)−B` on the cell margin (tan tile
   corners are a neutral reference — no die there), `pinkglitch = pink fraction in the border
   ring`, `dark = dark_frac`. Any of these over threshold → that cell's observation is
   `unknown`, others stay valid. White-balance *per cell* using the tile-corner reference
   instead of the board mean.
3. **`CellTracker`** (new module `perception/tracker.py`): for each of 15 cells keep
   `(type, conf, age, streak)`. Update rule:
   - observation `unknown` → keep belief, `age += 1`.
   - observation == belief → `conf = min(1, conf + p)`, `streak = 0`.
   - observation != belief → `streak` of the *same* new type; switch belief only when
     `streak ≥ K` (K = 3 for normal cells, 8 for Predator fixed cells — this generalizes
     today's `locked`/`wrongrun` logic to all cells and removes it from `bot_live.py`).
   - **Action-aware resets**: after `summon`, only `empty` cells may become non-empty →
     other cells' K doubles. After `switch(from,to)`, expected beliefs are swapped and K for
     those two cells drops to 1. After `merge/destroy`, the source cell is reset to `empty`
     with low conf. This is where the "the switch left #frm" check in `switch_verified`
     belongs, and it makes swap verification independent of the destination's glow.
4. `plan_next` consumes the tracker's belief board, plus a `confidence` per cell; cells
   below a floor are *not* moved (never swap into/out of an uncertain cell).

Expected effect: effect frames stop producing actions at all; the bot only acts on beliefs
that survived several clean observations. This alone should remove most churn.

### Layer B — Fix the data, then the metric (~1–2 days, mostly automated)
1. **Temporal label propagation** to label the hard crops for free: replay the recorded
   sessions (`data/sessions/*`, frames + action log). For each cell, run the Layer-A tracker;
   a crop taken while the cell's belief is high-confidence *before and after* it, with no
   action touching that cell in between, inherits that label — including the glow/glitch/
   buff frames in the middle. This converts the `_unlabeled` pile into labelled hard examples
   without manual review, and it is *also* the source for pip-2+ crops (pip only changes on
   merge, which is an action we log).
2. **Split by battle, not by crop** (`GroupShuffleSplit` on session/battle id). Keep one
   whole battle as the hard eval set. Report accuracy separately on `clean` vs `effect`
   crops (the effect flag from A.2) — the effect number is the one that matters.
3. Stop the `CAP=500` subsampling (Light 3,130 → 500 throws away the diverse cases);
   `class_weight="balanced"` already handles imbalance.
4. Manually verify ~200 propagated labels once (montage + `_unlabeled_order.txt` style) to
   measure propagation error before trusting it.

### Layer C — A model that is invariant to the overlays (~2–3 days, after B)
Once hard examples exist, swap the feature stack:

- **Preferred: tiny CNN on the raw 64×64 RGB crop** (3 conv blocks, ~50k params; ONNX or
  torch CPU — 15 crops per frame is < 5 ms). Train with augmentation that *synthesizes every
  effect we have seen*, not just `Dice_Glow`: hue rotation ±15°, per-channel gain (yellow/blue
  cast), additive pink/red/green translucent blobs, random 2–4 digit strings in the Predator
  font region, random purple pip-dot clusters (1–7), random darkening (popup veil), and the
  APK effect sprites (extract `Buff_*`, `Glitch_*`, arrow sprites from the same bundle as
  `Dice_Glow3`). Predict 7 classes + an `unknown`-friendly calibrated softmax.
- **Fallback if torch is not available on Python 3.14:** keep sklearn but change the
  features to ones that survive overlays: (a) circular hue histogram of the *frame ring
  only* (18 bins, S-weighted), (b) same for the *bottom band*, (c) pip-dot count & colour,
  (d) HOG of the *frame ring* only (the die frame shape is constant; the face is not), and
  drop the face-hue fractions. Then `HistGradientBoosting` instead of RF for calibrated
  probabilities.
- Two-stage head: stage 1 `die / empty / bomb / unknown`, stage 2 among the 5 deck types
  only when stage 1 says `die`. The board-level "≥ 12 cells same type → unreliable" guard
  becomes unnecessary.

### Pip (pip-2) handling — piggybacks on the above
The purple pip clusters are clearly visible even under glow (`_unlabeled` montage #2, #7, #17,
#28, #38…). Re-enable `count_pips` for Light/Bubble/Switch via purple blob count on the face,
but feed it through the tracker (pip belief with its own K) rather than trusting one frame.
Predator/Resonance pip stays "1 unless a merge action touched the cell".

---

## 3. Concrete code deltas (for Claude Code)

| File | Change |
|------|--------|
| `perception/board.py` | `classify_type` → return `predict_proba` max; add `("unknown", p)` path; replace global `_debuff_cast`/`glary` with per-cell `cell_effects(crop)`; per-cell white balance from tile-corner reference. |
| `perception/tracker.py` (new) | `CellTracker.update(observations, last_action)`; `belief()`; `confidence()`. Encodes K-streak rules and action-aware resets. |
| `tools/bot_live.py` | Delete `locked`/`wrongrun`/`switch unconfirmed` blocks; call `tracker.update()` after each grab; `plan_next(tracker.belief(), ...)`; `switch_verified` checks tracker instead of `read_board_stable(n=2)`. |
| `tools/propagate_labels.py` (new) | Offline: sessions → tracker replay → labelled crops into `data/crops_v2/<class>/` with `battle_id` in filename; writes `effect` flag sidecar. |
| `tools/train_recognizer.py` | Group split by battle; no CAP; report clean/effect accuracy separately; calibrated probs (`CalibratedClassifierCV` or HGB). |
| `tools/eval_hard.py` (new) | Runs the model on the held-out battle, prints confusion split by effect flag; this is the gate for "recognition is fixed". |

Verification gates (in order): (1) tracker unit tests — a glow burst of 10 frames on a locked
Predator changes nothing; a real swap is accepted in 1 frame after `switch`. (2) effect-crop
accuracy ≥ 0.9 on the held-out battle. (3) live: 0 Predator moves in 3 battles, 8/8 fixed
reached, no "board read unreliable — skip" lines.

## 4. Things to leave alone
- Grid geometry, `is_battle`, `is_game_over`, injection, the policy engine — all verified and
  not the source of the problem.
- Don't add more hue-band rules. Every new band is a new thing an effect can land in.
