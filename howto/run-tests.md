---
title: Run the tests
type: howto
updated: 2026-10-23
sources: [seed]
---
# Run the tests

Use pytest from the repo venv: `.venv\Scripts\python.exe -m pytest tests/`. The older
`python -m unittest discover -s tests -v` skips `tests/test_policy_gear.py`.

## Details
- Most tests were written as stdlib `unittest` (the Cowork container could not reach PyPI); pytest
  runs them unchanged.
- `tests/test_policy_gear.py` has 32 bare `def test_*` functions and no `unittest.TestCase`, so
  only pytest collects it.
- Install once: `pip install -e .` (docs/04, docs/06).
- Test files: encoder, events, frames_index, geometry, geometry_fit, policy, policy_gear,
  replay_overlay, sim, tracker, verify.
- Planned recognizer gate (not yet written): `tools/eval_hard.py` on a held-out battle.

## Evidence
- `docs/04_HANDOFF_R1_R5_VERIFY.md` — `pip install -e .`, `python -m unittest discover -s tests -v`, note that `pytest tests/` also works
- `docs/06_HANDOFF_R8_VERIFY.md` — same commands
- `tests/test_policy_gear.py` — pytest-style functions only
- `CLAUDE_CODE_TODO.md` — "pip 네트워크 불가" (why unittest)
