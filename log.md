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

## 2026-10-29 · rdf01-t3 · milestone tracker and support judge
- Added pure policy/milestones.py (MilestoneTracker: reached/late milestones, score crossings) and tools/support_judge.py (4-of-5 verdict from data/support_rounds.jsonl, exit 0/1/2).
- pages: components/policy-milestones.md (new)

## 2026-10-29 · rdf01-t4 · score reader and generic digit kinds
- Added perception/score.py (read_score exact-or-None, ScoreTracker 2-read confirm); SCORE_BOX is None and digits_score.npz absent until measured later.
- build_digit_templates.py gained build_kind and a kind-name CLI; room/hp moved into main() unchanged.
- pages: components/perception-score.md (new)

## 2026-10-29 · rdf01-t5 · support-deck perception
- Added perception/support.py with its own support_*.pt models (gear TYPES untouched), pip_source auto/gear, star-based pip 7, sha256-verified gate_state (unlisted support model also turns the gate off), deck bar, power cards, card level (LV_BOX None until measured).
- pages: components/perception-support.md (new)

## 2026-10-29 · rdf01-t6 · capture safety and support writers
- Added LiveGrabber.unobscured() (z-order overlap check, fail closed) and collect.save_support_cells/save_frame that write nothing when covered; tools/save_frame.py. Not yet called by any bot loop.
- pages: components/capture-live.md (updated)

## 2026-10-29 · rdf01-t7 · support labelling tools
- Added offline support_prelabel (gear model + colour rule, star candidates), support_review (50-crop sheets, stratified holdout) and build_support_tag (chk only for ticked sheets).
- pages: components/labelling-support.md (new)

## 2026-10-29 · rdf01-t8 · support trainers and R4 gate
- Added train_support_type_cnn/star/pip (atomic save, games recorded in support_train_manifest.json) and support_gate.py (held-out chk-only metrics, manifest refusal, support_gate.json with model sha256).
- pages: components/training-support.md (new)

## 2026-10-29 · rdf01-t9 · support bot core
- Added tools/support_bot.py: route_deck (2 consecutive deck-bar hits in 20 frames), per-call unobscured Saver, R4 choose_mode, R14 build_record/append_round, run_battle with wrong_deck hand-over and call-time support_play lookup.
- pages: components/support-bot-core.md (new)

## 2026-10-29 · rdf01-t10 · support players
- Added tools/support_players.py: Perception wrappers, BasePlayer (fixed tick priority, 15 s cells / 30 s frame cadence via Saver), CollectPlayer (summon, one power-panel snapshot at 120 s, never buys).
- pages: components/support-players.md (new), components/support-bot-core.md (updated)

## 2026-10-29 · rdf01-t11 · PlayPlayer board play
- Added PlayPlayer to tools/support_players.py: two-read and 4-read buffed guards, junk limit, type-keyed 90 s merge ban, 130 s supporter cooldown, banner timers (clone 45 s, power hold 65 s), trial = gear pips, provisional close-only panel_hook.
- pages: components/support-players.md (updated)

## 2026-10-29 · rdf01-t16 · PlayPlayer power-ups, milestones, play() and main()
- PlayPlayer now has the power bar (20 s, hold deadline), the R20 power visit (two level reads 0.3 s apart) and score/milestone events with screenshots; support_bot gained play() and a dry-run-by-default main().
- pages: components/support-players.md (updated), components/support-bot-core.md (updated)

## 2026-10-29 · rdf01-t12 · offline support dry run
- Added tools/support_dryrun.py (frame PNG -> board rows, evaluate, planned action with support_ready=True, score); no input, no inject import. Without models: 15 junk cells, op wait, score None.
- pages: howto/run-bot.md (updated)
