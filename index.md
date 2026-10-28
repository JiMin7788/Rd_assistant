# rdom wiki

## Components
- [Live screen capture](components/capture-live.md) — dxcam grab of the content rect, window-move check, hang watchdog (2026-10-23)
- [Input injection (M2)](components/input-inject.md) — PostMessage taps/swipes to GPG, dry-run default, UI coordinates (2026-10-23)
- [Board perception and cell tracker (Predator deck)](components/perception-board.md) — board.py reads + screen states, Layer A belief tracker (2026-10-23)
- [Gear-deck perception](components/perception-gear.md) — CNN type/pip models, deck detection, UI templates, OCR banners (2026-10-23)
- [Rule-based policy engines (M3)](components/policy.md) — target.py (Predator) and gear.py (current) rule engines (2026-10-23)
- [Support-deck rule engine](components/policy-support.md) — policy/support.py: merge/supporter rules, [decks.support] config, not yet wired (2026-10-29)
- [Power-up order policy](components/policy-power.md) — policy/power.py: Growth to 7, Alignment:Resonance 3:1, Growth 8 later, maxed detection (2026-10-29)
- [Safety guards and stop switches](components/safety-guards.md) — dry-run, battle/window guards, failure limits, PAUSE/STOP (2026-10-23)

## Decisions
- [Rule-based bot, no BC/RL (2026-09-16)](decisions/rule-based-bot-no-rl.md) — M5/M6/M7 dropped; perception + input + rule engine only (2026-10-23)
- [Content-normalised (u,v) coordinates; window messages instead of adb](decisions/input-coordinates.md) — one coordinate space; GPG PostMessage since 2026-10-16 (2026-10-23)

## Howto
- [Run the bot (launchers, dry-run, live)](howto/run-bot.md) — .bat launchers, run_all/supervisor, dry-run entry points (2026-10-23)
- [Run the tests](howto/run-tests.md) — pytest from the venv; unittest misses test_policy_gear (2026-10-23)

## Lessons
- [Recognition pitfalls (effects, glare, pips, empty cells)](lessons/recognition-pitfalls.md) — why live reads fail and the guards that fixed them (2026-10-23)
- [Capture and runtime pitfalls](lessons/capture-and-runtime-pitfalls.md) — chrome, stretch, stale/hung dxcam, jitter, popups (2026-10-23)
- [A recorded session captured secrets](lessons/session-secret-exposure.md) — session deleted, credentials rotated; keep captures clean (2026-10-23)
