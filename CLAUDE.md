# CLAUDE.md — rdom

Rule-based bot for a dice tower-defense game running on Google Play Games (PC). Perception (screen
capture + small CNNs/OCR) → rule engine → window-message input. Production = the gear-deck coop loop,
controlled from Discord. Read once per session, not re-explained.

## Session Start

1. Read `.agent-state/state.json`; tail the last line of `.agent-state/history.jsonl` only when needed.
2. Summarize `phase` + `focus` + `next_action` to the human in 1-2 Korean lines. Do not re-explain the project.
3. Before touching an area, read `wiki/index.md` and at most 3 relevant pages (`wiki` skill, *query*).

## Behavioral Guidelines

Think before coding (state assumptions, ask when unclear) · simplicity first · surgical changes · goal-driven
(every change has a check: a test, a dry-run on a saved frame, or a logged live observation).

## Language Policy

Code, docs, wiki, history: English. Human-facing summaries: Korean, 1-2 lines. `CLAUDE_CODE_TODO.md` is in Korean
already; keep its language.

## Hard Rules (auto-FAIL)

- **R1 dry-run by default** — `Injector(execute=False)`; real input only behind `--execute`.
- **R2 guards stay on** — no board action unless `is_battle`; stop if the game window moved; an action needs two
  identical consecutive reads; stop after 3 consecutive rounds that fail to start; the supervisor stops after 5 crashes in 30 min
  (anomaly → stop and fix, never blind restarts).
- **R3 rules, not learning** — no BC/RL policy (decision 2026-09-16); strategy = the user's written rules.
- **R4 recognizer gate** — a new recognizer goes live only with held-out effect-crop accuracy ≥ 0.9; no new
  hue-band rules (`docs/07_RECOGNITION_REVIEW.md`).
- **R5 secrets** — never print, record or commit `config/discord.toml`; never capture frames with other windows
  over the game (a session once captured credentials — `wiki/lessons/session-secret-exposure.md`).
- **R6 window config** — do not move/resize the game window or change chrome insets without updating
  `config/recorder.toml` and the wiki.

## Verification

`.venv\Scripts\python.exe -m pytest tests/` (not `unittest discover`: it skips the pytest-style
`tests/test_policy_gear.py`). Live behavior: dry-run first (`python tools/gear_bot.py`), then `--execute` only
with the human present.

## Loop

`Lead picks one item (state next_action / CLAUDE_CODE_TODO.md) → Agent implements + tests → independent Reviewer
(fresh context) returns JSON {"task","verdict":"PASS|FAIL","issues":[]} → PASS: Agent runs the wiki update,
wiki-reviewer checks it → commit, history.jsonl += 1 line, state.json fields replaced / FAIL: re-issue with issues
/ 3 FAILs: halt for human`. Live-game checks are human-gated → `CLAUDE_CODE_TODO.md`.

## Document Map

| Purpose | Doc |
|---|---|
| Game rules, UI, current emulator (GPG) | `docs/01_GAME_SPEC.md` |
| Strategy notes / pre-research (ToS risk §6) | `docs/02_STRATEGY.md`, `docs/00_PRE_RESEARCH.md` |
| Recorder spec + amendments | `docs/03_RECORDER_SPEC.md`, `docs/05_AMENDMENTS.md` |
| Recognition redesign (layers A/B/C) | `docs/07_RECOGNITION_REVIEW.md` |
| As-built knowledge — how it works now, why, pitfalls | `wiki/index.md` (format: `wiki` skill) |
| Open items / human-gated checks | `CLAUDE_CODE_TODO.md` |
