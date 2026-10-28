# Wiki log

## 2026-10-23 · seed · initial wiki from docs and CLAUDE_CODE_TODO
- Seeded from `CLAUDE_CODE_TODO.md`, `docs/00`–`07`, configs, launchers and the current `src/`/`tools/` code.
- Code is newer than the TODO: production is the gear-deck loop on Google Play Games with PostMessage input (no adb).
- pages: components/capture-live.md, components/input-inject.md, components/perception-board.md, components/perception-gear.md, components/policy.md, components/safety-guards.md, decisions/rule-based-bot-no-rl.md, decisions/input-coordinates.md, howto/run-bot.md, howto/run-tests.md, lessons/recognition-pitfalls.md, lessons/capture-and-runtime-pitfalls.md, lessons/session-secret-exposure.md (all new)

## 2026-10-23 · seed-review · independent review fixes
- wiki-reviewer PASS (64 claims checked); 1 minor fixed: gear_loop failure limit counts rounds that fail to start.
- pages: components/safety-guards.md (updated)

## 2026-10-29 · rdf01-t1 · support-deck rule engine
- Added pure engine policy/support.py (plan_support etc.) plus config/deck.toml `force` and [decks.support] (after decay so deck_name() fallback stays doom).
- pages: components/policy-support.md (new), components/policy.md (updated)

## 2026-10-29 · rdf01-t2 · power-up order policy
- Added pure policy/power.py (next_card, plan_visit, PowerTracker with 2-strike maxed detection) and power_* keys in [decks.support].
- pages: components/policy-power.md (new)
