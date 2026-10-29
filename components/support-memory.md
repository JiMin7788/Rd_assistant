---
title: Support-deck cell memory
type: component
updated: 2026-10-29
sources: [rdf02-t4]
---
# Support-deck cell memory

`perception/support_memory.py` is a pure module (no cv2, torch or I/O) that builds an "effective board" from raw support reads: a hacked die reads as junk but keeps its type and pip, so the last confirmed value is remembered until the cell really changes. Not yet called by any player; later rdf02 tasks wire it in.

## CellMemory(conf_min, confirm=2)
- A read is unreadable when `type == "junk"` or `conf < conf_min` (`unreadable(d)`); `conf_min` is a parameter (callers pass `support.READ_CONF_MIN`, see [support perception](perception-support.md)).
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
`tests/test_support_memory.py` covers each rule and event (hacked die over 10 junk ticks gives one `remembered`; low-conf empty is unknown; Growth not external; external forgets only currently unreadable cells; own-action expiry; burst ties and empty).

## Evidence
- commit `19fc3e4` (branch task/rdf02-t4, not yet merged into this checkout when written) — adds perception/support_memory.py (CellMemory, burst_result, merge_verdict, _external; own-action and Growth exemption in update) and tests/test_support_memory.py (one test group per rule above).
