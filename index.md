# rdom wiki

## Components
- [Live screen capture](components/capture-live.md) — dxcam grab of the content rect, window-move check, hang watchdog, unobscured check + support crop/frame/burst writers, save_frame tool never overwrites (2026-10-29)
- [Input injection (M2)](components/input-inject.md) — PostMessage taps/swipes to GPG, dry-run default, UI coordinates (2026-10-23)
- [Board perception and cell tracker (Predator deck)](components/perception-board.md) — board.py reads + screen states, Layer A belief tracker (2026-10-23)
- [Gear-deck perception](components/perception-gear.md) — CNN type/pip models, deck detection, UI templates, OCR banners, dice info panel detector (2026-10-30)
- [Rule-based policy engines (M3)](components/policy.md) — target.py (Predator) and gear.py (current) rule engines (2026-10-23)
- [Support-deck rule engine](components/policy-support.md) — policy/support.py: merge/supporter rules, [decks.support] config, not yet wired (2026-10-29)
- [Power-up order policy](components/policy-power.md) — policy/power.py: Growth to 7, Alignment:Resonance 3:1, Growth 8 later, SP reserve keep(), count-based levels with Lv cross-check, confirmation-based maxed (2026-10-30)
- [Support-deck milestone tracker and judge](components/policy-milestones.md) — policy/milestones.py m1/m2/m3 + crossings, tools/support_judge.py 4-of-5 verdict, --last>=1, zero games = cannot judge (2026-10-29)
- [Score reader and generic digit-template kinds](components/perception-score.md) — perception/score.py read_score + ScoreTracker, build_kind for digits_<kind>.npz; SCORE_BOX + digits_score.npz measured on H1, check_support_assets.py score/deck bar/power cards/lv box lines; tracker rejects negative/>99999/lower reads; read_score layout_ok/views_agree (lowest threshold only)/MIN_MARGIN refuse painted-over digits; reader numbers re-measured after s4/s18 (score 49/49); sp.py read_sp/read_summon_cost with SP_BOX/COST_BOX and sp/cost check lines, read_panel_sp/read_price (min-channel on green button) for the power panel; sp._undim stretches dimmed crops (2026-10-30)
- [Support-deck perception](components/perception-support.md) — perception/support.py: support board + pip source/star, R4 gate_state, deck bar, power cards, card level, read_cells_support, READ_CONF_MIN 0.90 (support_conf_report.py), STAR_THRESHOLD 0.7 (gate numbers cited from support_gate.json), once-only missing-model warning, grey-safe deck detection; templates and LV_BOX measured on H1; not yet wired (2026-10-30)
- [Support-deck cell memory](components/support-memory.md) — perception/support_memory.py: CellMemory effective board for hacked/unreadable cells, own-action marks, external-change forgetting, burst_result, merge_verdict; pure, used by PlayPlayer (2026-10-29)
- [Support-deck labelling tools](components/labelling-support.md) — support_prelabel / support_review / build_support_tag: gear+colour+seed-kNN pre-labels, check_prelabel, 50-crop sheets, chk-flagged tags, fixes.tsv validation; offline only (2026-10-29)
- [Support-deck trainers and R4 gate](components/training-support.md) — train_support_{type_cnn,star,pip}, train manifest, support_gate.py held-out pass flags + sha256 JSON, star cut = support.STAR_THRESHOLD (a change needs a gate re-run) (2026-10-30)
- [Support bot core](components/support-bot-core.md) — tools/support_bot.py: route_deck, Saver (cells/frame/burst), choose_mode, round record, run_battle with wrong_deck hand-over, play() and dry-run main(); wired into gear_loop/gear_bot, clear at 5000, gear_loop lobby guard incl. round-start leave_result_screen, final_score always in the record (null if unread), gear_loop importable with main()/after_battle (2026-10-30)
- [Support players](components/support-players.md) — tools/support_players.py: Perception wrappers, BasePlayer tick priority + data cadence, CollectPlayer, PlayPlayer board play with effective board, bursts (R7.4 forgets blank the board) and merge verification, Burster burst mechanics, dice info panel (bands, thresholds, banner overlap) closed by tapping 소환, game over confirmed on 2 ticks with battle UI gone, SP-based power trigger and one-card-at-a-time confirmed buying (SP unreadable checked before unknown keep), panel SP read retried up to 1 s, stale SP after a level-confirmed buy not carried, gameover_once saves the result-like frame (2026-10-30)
- [Safety guards and stop switches](components/safety-guards.md) — dry-run, battle/window guards, failure limits, PAUSE/STOP (2026-10-23)

## Decisions
- [Rule-based bot, no BC/RL (2026-09-16)](decisions/rule-based-bot-no-rl.md) — M5/M6/M7 dropped; perception + input + rule engine only (2026-10-23)
- [Content-normalised (u,v) coordinates; window messages instead of adb](decisions/input-coordinates.md) — one coordinate space; GPG PostMessage since 2026-10-16 (2026-10-23)

## Howto
- [Run the bot (launchers, dry-run, live)](howto/run-bot.md) — .bat launchers, run_all/supervisor, dry-run entry points, support-deck offline frame check, run_all SHOW lines, H2 runbook, H3 (R14) runbook, support_dryrun --data-dir (2026-10-30)
- [Run the tests](howto/run-tests.md) — pytest from the venv; unittest misses test_policy_gear (2026-10-23)

## Lessons
- [Recognition pitfalls (effects, glare, pips, empty cells)](lessons/recognition-pitfalls.md) — why live reads fail and the guards that fixed them (2026-10-23)
- [Capture and runtime pitfalls](lessons/capture-and-runtime-pitfalls.md) — chrome, stretch, stale/hung dxcam, jitter, popups (2026-10-23)
- [A recorded session captured secrets](lessons/session-secret-exposure.md) — session deleted, credentials rotated; keep captures clean (2026-10-23)
