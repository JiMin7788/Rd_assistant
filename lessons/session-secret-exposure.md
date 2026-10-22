---
title: A recorded session captured secrets
type: lesson
updated: 2026-10-23
sources: [seed]
---
# A recorded session captured secrets

A capture session recorded another window with credentials over the game area; the session had to be
deleted and the exposed keys/passwords rotated. Screen recordings and crops are sensitive data.

## What to do
- Before recording or sharing frames, make sure nothing else overlaps the captured screen region.
- Recorded data stays local: `data/` is gitignored; never train on, share or upload a session that
  captured anything outside the game.
- Discord credentials live only in `config/discord.toml` (gitignored); never print, log or commit them.
- If a leak is found: delete the session, then rotate every exposed credential.

## Evidence
- `CLAUDE_CODE_TODO.md` — M1 item "보안: 세션 삭제 완료 (2026-09-16) … 회전 필요"
- `docs/02_STRATEGY.md` — M1 real-data validation note (session to be discarded, credentials to rotate)
- `.gitignore` — `data/`, `config/discord.toml`
