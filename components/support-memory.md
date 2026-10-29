---
title: Support-deck cell memory
type: component
updated: 2026-10-29
sources: [rdf02-t4, rdf02-t6, rdf02-m1]
---
# Support-deck cell memory

`perception/support_memory.py` is a pure module (no cv2, torch or I/O) that builds an "effective board" from raw support reads: a hacked die reads as junk but keeps its type and pip, so the last confirmed value is remembered until the cell really changes. `PlayPlayer` in `tools/support_players.py` uses it since rdf02-t6 (effective board, bursts, merge verification on raw reads); see [support-players](support-players.md). CollectPlayer does not.

## CellMemory(conf_min, confirm=2)
- A read is unreadable when `type == "junk"`, `conf` is not a finite number, or `conf < conf_min` (`_unreadable(d, conf_min)`); the finite check exists because `NaN < conf_min` is False and a NaN read would otherwise count as confident. `burst_result` never accepts a non-finite conf, and `Burster.done` uses the same predicate ([support-players](support-players.md)). `conf_min` is a parameter (callers pass `support.READ_CONF_MIN`, see [support perception](perception-support.md)).
- `update(raw)` takes 15 raw dicts (cell = `d["cell"]`, else position+1) and returns `(effective, events)`. Effective entries copy the raw dict with a `src`:
  - readable cell: raw read, src `read`;
  - unreadable with memory: memory type/pip, raw conf, src `memory`;
  - unreadable without memory: type `junk`, pip 0, src `unknown`. A low-conf `empty` read is therefore never `empty`.
- Memory is set by `confirm` identical confident reads of a non-empty value. A different confident value (or confident empty) only replaces/drops the memory after `confirm` identical reads in a row; one noisy read changes nothing. Unreadable ticks leave the pending count untouched.
- Replacing a non-Growth memory on a cell not marked own-action is an external change (R7.4): the memory and pending count of every cell unreadable in that raw board are dropped, and one `external` event `{cells, forgot}` is emitted (plus one `unknown` per forgotten cell). Growth grows by itself, so its replacement is never external.
- `own_action(cells, ticks=5)` marks cells for that many `update()` calls (counter decremented at the end of each update). A replacement on a marked cell is normal (memory still replaced) but emits no external event and forgets nothing. `supported(cell)` drops the cell and marks it; `merged(fr, to)` drops both cells (memory and pending). A merge that was not reported via `merged` keeps memories.
- Events fire on entering a state, not every tick: `remembered {cell, tok}` (tok = `type[:2]` + pip, e.g. `Re3`), `unknown {cell}` when a memory is dropped while remembered, `external`.
- `apply_burst(cell, value, unreadable_cells)`: `None` returns `(None, [])` and changes nothing. An accepted die value sets the memory (src `burst`; if it differs from a non-Growth, non-marked memory, the R7.4 external handling applies, with the other unreadable cells); an accepted `("empty", 0)` drops the memory and returns an effective empty read.

## Functions
- `burst_result(reads, conf_min, agree=2)`: confident reads (not junk, conf >= conf_min) grouped by `(type, pip)` (empty is `("empty", 0)`); a group needs reads from >= `agree` grabs. Several groups: highest single conf, then larger group, then earlier first read. Returns `(type, pip)` or None. Assumes the caller already dropped pixel-identical grabs, so each read counts as a separate grab.
- `merge_verdict(raw_from, raw_to, before_from, before_to, conf_min)` on RAW reads: `effect` if any confident read differs from its before value (including a confident empty from-cell); `none` only if both are confident and equal to before; otherwise `undecided`. An unreadable read never counts as unchanged.

## Tests
`tests/test_support_memory.py` covers each rule and event (hacked die over 10 junk ticks gives one `remembered`; low-conf empty is unknown; Growth not external; external forgets only currently unreadable cells; own-action expiry; burst ties and empty). `tests/test_support_m1_inputs.py` covers the non-finite conf rule; `tests/test_support_play_m1.py` shows through a fake PlayPlayer that a Joker copy merge and a bomb merge with verdict `effect` drop both cells' memories like a normal merge.

## Evidence
- commit `2e74942` (branch task/rdf02-m1) — `_finite` and the non-finite clause in `_unreadable` in perception/support_memory.py; tests `test_nan_conf_is_unreadable_in_update`, `test_burst_result_never_accepts_non_finite_conf` in tests/test_support_m1_inputs.py and `test_joker_copy_and_bomb_merge_drop_both_memories` in tests/test_support_play_m1.py (no code change was needed for the merge test).
- commit `19fc3e4` (branch task/rdf02-t4, not yet merged into this checkout when written) — adds perception/support_memory.py (CellMemory, burst_result, merge_verdict, _external; own-action and Growth exemption in update) and tests/test_support_memory.py (one test group per rule above).
- `tools/support_players.py` — PlayPlayer calls `update`, `apply_burst`, `own_action`, `supported`, `merged`, `merge_verdict`, `burst_result` (rdf02-t6, commit `78aa900`).
