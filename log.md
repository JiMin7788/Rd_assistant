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

## 2026-10-29 · rdf01-t13 · integration into gear_loop and gear_bot
- gear_loop now calls support_bot.run_battle (keyword args, gear_play=play) and reloads support models; gear_bot hands over with "wrong_deck" when the support deck bar is seen (first tick, then every 10 s, before all other rules); run_all SHOW and deck.toml comments extended; H1-H3 runbook added to CLAUDE_CODE_TODO.md.
- pages: components/support-bot-core.md (updated), howto/run-bot.md (updated)

## 2026-10-29 · rdf01-i1 · integration fixes round 1
- PowerTracker.start_visit gained `found`: a card not on the panel is level None and does not force src `count`; record levels are null only for cards never found in the game. Runbook now trains star/pip models for seeds 1-3.
- pages: components/policy-power.md (updated), components/support-players.md (updated)

## 2026-10-29 · rdf01-r2-s6 · equal-pip merge tie-break
- `_best_merge` equal-pip order is now Adjust+Resonance/Alignment > other pairs > Adjust+Bubble (QA S6: a plain Alignment pair used to win).
- pages: components/policy-support.md (updated)

## 2026-10-29 · rdf01-r3-s23 · support_review --ambiguous prints paths
- `--ambiguous` now prints each newly cut sheet PNG path and the index.tsv path after the count line (QA S23).
- pages: components/labelling-support.md (updated)

## 2026-10-29 · rdT01 · Support-deck tool hardening
- ScoreTracker ignores negative, >99999 and lower-than-confirmed reads; judge rejects --last<1 and zero games = cannot judge; build_support_tag validates fixes.tsv lines and counts ignored; gate prints real path; missing max_score prints `?`.
- pages: components/perception-score.md (updated), components/policy-milestones.md (updated), components/labelling-support.md (updated), components/training-support.md (updated)

## 2026-10-29 · rdF01-H1 · force support deck
- no wiki-worthy change (config/deck.toml `force = "support"` for H1 collection; temporary, to be reverted to "").

## 2026-10-29 · rdF01-H1 · clear force
- no wiki-worthy change (config/deck.toml `force` back to "" after H1 collection; deck bar detection is the default again).

## 2026-10-29 · rdT02 · Support prelabel seed kNN
- support_prelabel gained a seed kNN step (gear-CNN block-3 features vs eye-checked seeds) for white/cream Resonance and Alignment, a slime guard, and --out; new tools/check_prelabel.py scores against assets/prelabel_eval_h1.tsv. Corrected page: the seed step runs after the colour rule, not before.
- pages: components/labelling-support.md (updated)

## 2026-10-29 · rdf02-t1 · score calibration from H1 frames
- SCORE_BOX measured (0.36, 0.083, 0.64, 0.126) and digits_score.npz committed; read_score accepts 2-D grey input; new tools/check_support_assets.py prints the score and score-lobby lines (n=42 correct=38 none=4 wrong=0; lobby none=1/1).
- pages: components/perception-score.md (updated)

## 2026-10-29 · rdf02-t2 · deck-bar and power-card templates, LV_BOX
- Committed deck_support.png and the Resonance/Alignment/Growth card icons (no Alignment _b look exists on the panel); LV_BOX measured on the five H1 panels; check_support_assets.py gained --out-dir and the deck bar / power cards / lv box lines (181/181, 5/5, 5/5).
- pages: components/perception-support.md (updated), components/perception-score.md (updated)

## 2026-10-29 · rdf02-t3 · per-cell support reading and READ_CONF_MIN
- Added read_cells_support (given cells, same result as the board entry; read_board_support now calls it) and READ_CONF_MIN = 0.90 measured by new tools/support_conf_report.py on holdout sup20261029_152652 (kept 99.5%, accuracy of kept 0.997).
- pages: components/perception-support.md (updated)

## 2026-10-29 · rdf02-t4 · CellMemory, burst_result, merge_verdict
- Added pure perception/support_memory.py: per-cell memory keeps a hacked die's last confirmed value (2 identical reads), unreadable-without-memory is junk/unknown, external change forgets unreadable cells (Growth and own-action cells exempt), burst_result needs 2 agreeing grabs, merge_verdict on raw reads.
- pages: components/support-memory.md (new)

## 2026-10-29 · rdf02-t5 · Burst capture and saving
- Added collect.save_burst (72/128 px burst crops + bursts.jsonl, nothing written when covered), Saver.burst, Perception.read_cells_support/frames_equal, and Burster (due/run/done/record/maybe_save: 6 frames 0.08 s apart, repeat frames dropped, fail backoff, save cap 60). Not yet called by a player.
- pages: components/support-players.md (updated), components/capture-live.md (updated), components/support-bot-core.md (updated)

## 2026-10-29 · rdf02-t6 · PlayPlayer effective board, bursts, merge verification
- PlayPlayer now plans on the CellMemory effective board, runs bursts for unreadable cells, verifies merges with merge_verdict on RAW reads (undecided x3 counts as effect), guards on raw unreadable count, prints memory/burst log lines, adds stats bursts/burst_hits/mem_ticks/forgets.
- pages: components/support-players.md (updated), components/support-memory.md (updated)

## 2026-10-29 · rdf02-t7 · H2 readiness
- tools/save_frame.py claims names with exclusive create (_2.._99), never overwrites; run_all SHOW echoes cell-memory lines; H2 runbook and H1-done note in CLAUDE_CODE_TODO.md.
- pages: components/capture-live.md (updated), howto/run-bot.md (updated)

## 2026-10-29 · rdf02-i1 · integration fixes round 1
- _burst now blanks cells forgotten by an R7.4 external event from apply_burst on this tick's effective board (before, only the burst cell was replaced), so a forgotten die cannot be merged on a "stable" board.
- pages: components/support-players.md (updated)

## 2026-10-29 · rdf02-i2 · integration fixes round 2
- check_support_assets.py now writes the lv box overlays to `<data-dir>/support_frames/_check` by default (spec R4), not a temp folder.
- pages: components/perception-score.md (updated)

## 2026-10-29 · rdf02-r2-s12 · read_cells_support rejects out-of-range cells
- read_cells_support raises ValueError for any cell outside 1..15; before, cell 0 / negatives indexed the crop list from the end and returned another cell's read under the wrong label.
- pages: components/perception-support.md (updated)

## 2026-10-29 · rdf02-m1 · QA round 3 follow-up
- Non-finite conf is unreadable everywhere (CellMemory, burst_result, Burster.done backoff); read_cells_support rejects bool/non-int cells; `--help` no longer writes digits_--help.npz; conf_report prints one FAIL line for a missing feats tag; tests prove Joker/bomb merges drop both memories and covered-window bursts still feed the board but save nothing.
- pages: components/support-memory.md (updated), components/support-players.md (updated), components/perception-support.md (updated), howto/run-bot.md (updated)

## 2026-10-30 · rdT03 · close the dice info panel by tapping 소환
- Tapping a field die opens the dice info panel, which made every cell unreadable; gear.dice_info_panel (share of V < 60 pixels, u 0.08-0.92, in bands v 0.03-0.15 / 0.20-0.28 / 0.52-0.585, each >= 0.40 / 0.60 / 0.70; middle v 0.30-0.51 left out because a boss banner can cover it; band 2 overlaps the banner band v 0.165-0.265, banner alone 0.48-0.59 vs 0.60; commit 4999025, merged c9f98ce) now triggers one 소환 tap (closes only, no summon) in BasePlayer.tick before the tactic check; repeat taps >= 1.0 s apart.
- pages: components/support-players.md (updated)

## 2026-10-30 · rdT04 · Support star threshold 0.7 shared constant
- support.STAR_THRESHOLD = 0.7 replaces the 0.5 literals in read_cells_support and support_gate._predict; 0.5 gave star precision 0.838 on the H2 holdout (source: STAR_THRESHOLD comment in support.py), 0.7 gives 0.954 at recall 0.984 (data/support_gate.json, gate re-run after rdT04).
- pages: components/perception-support.md (updated), components/training-support.md (updated)

## 2026-10-30 · rdf03-t2 · Confirmed game over, clear at 5000
- Support game stops only after 2 ticks of result look with battle UI gone (H2 06:39 false stop); look-alikes are logged/saved; a game_over with score >= 5000 is recorded as "clear" (+final_score); gear_loop skips the lobby tap if a battle is on screen; judge accepts clear.
- pages: components/support-players.md (updated), components/support-bot-core.md (updated)

## 2026-10-30 · rdf03-t3 · Battle SP and summon-cost readers
- perception/sp.py reads battle SP and the 소환 button cost exact-or-None with its own digits_sp/digits_cost templates; 2-digit costs read None because the Ø icon intrudes the box; the check tool skips crops cut with other boxes.
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-t4 · Power-panel readers
- Added read_panel_sp and read_price (PANEL_SP_BOX, PRICE_BOX); price reads the weakest RGB channel because white digits on the green button grey to ~180, near the 170 threshold; templates are thin (room fallback for most digits) until H3 panel frames.

## 2026-10-30 · rdf03-t5 · Power policy: SP reserve, count-based levels, Lv cross-check
- PowerTracker levels are now 1 + game-confirmed purchases; screen digits only cross-check (field-effect +1 detected, count kept); maxed needs 2 strikes with SP known and enough; keep() = power_reserve_x (3) * summon cost.
- PlayPlayer still counts every tap as confirmed with SP/keep unknown until rdf03-t6.
- pages: components/policy-power.md (updated)
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-t6 · PlayPlayer power wiring: SP trigger, confirmed one-at-a-time buying
- Power panel now opens on SP (2 consecutive reads) >= keep + next price with the cost confirmed on 2 ticks; the complete/idle triggers are removed. power_visit buys one card at a time above the reserve, each tap confirmed by an SP drop >= price/2 or a level rise; an unconfirmed tap ends the visit. BUY_MAX 10, PANEL_SAVE_MAX 20.
- pages: components/support-players.md (updated)

## 2026-10-30 · rdf03-t8 · rdF02 QA minors: missing-model warning, dry-run --data-dir, grey-safe deck detection
- read_cells_support warns once when support_type_cnn.pt is absent from _DATA (empty in a worktree); detect_support_deck returns False for non-HxWx3 uint8 input; support_dryrun gained --data-dir (sets support and gear _DATA, clears cached nets).
- pages: components/perception-support.md (updated), howto/run-bot.md (updated)

## 2026-10-30 · rdf03-t9 · Wiki fixes from the rdT03/rdT04 wiki reviews
- support-players now states the dice-info bands, `>=` thresholds, V < 60, u 0.08-0.92, the left-out middle band and the banner overlap as in gear.py, with commit 4999025 (merged c9f98ce); perception-gear names dice_info_panel; perception-support drops the uncited false-star cause and cites data/support_gate.json for the 0.7 numbers; training-support notes a STAR_THRESHOLD change needs a gate re-run. The code comments on `_INFO_BANDS` and `STAR_THRESHOLD` now carry the same evidence; the 0.838 at 0.5 is attributed to the Master's measurement on the same holdouts.

## 2026-10-30 · rdf03-t10 · H3 runbook and console SHOW lines
- CLAUDE_CODE_TODO.md: H2 marked done, H3 rewritten as the R14 acceptance procedure; run_all.py SHOW echoes six more play-mode lines.
- pages: howto/run-bot.md (updated)
- pages: components/support-players.md (updated), components/perception-gear.md (updated), components/perception-support.md (updated), components/training-support.md (updated)

## 2026-10-30 · rdf03-i1 · Panel SP read retry
- power_visit retries the panel SP read (0.25 s steps, up to 1 s) until two numeric reads exist, because a +30 popup hides the digits on most panel frames (2 of 6 readable); otherwise most visits closed as SP unreadable.
- pages: components/support-players.md (updated)

## 2026-10-30 · rdf03-m1 · gear_loop importable, after_battle tested
- tools/gear_loop.py: live code moved into main() (run under __main__); end-of-battle handling extracted to after_battle(); tests/test_gear_loop_result.py imports it through a booby-trapped fixture.
- pages: components/support-bot-core.md (updated)

## 2026-10-30 · rdf03-m2 · Integration review follow-up
- gear_loop round start no longer taps the lobby blindly when a battle is on screen (leave_result_screen); round record always has final_score (null if unread); power_visit does not carry a stale panel SP after a level-confirmed buy; gameover_once saves the result-like frame; runbook keeps gameover_*.png.
- pages: components/support-bot-core.md (updated), components/support-players.md (updated), howto/run-bot.md (updated)

## 2026-10-30 · rdf03-r2-s4 · read_score refuses irregular glyph layouts
- read_score now needs an even, centred, equal-height glyph row (layout_ok), a 0.12 template margin and the same glyph count at thresholds 170/190/210; painted-over digits give None instead of 667/2367/1980/4910. 1-D input returns None.
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-r2-s18 · SP and cost read on a dimmed battle
- A dice-info panel dims the battle (digits peak ~70), which made read_sp/read_summon_cost None; sp._undim stretches crops peaking in 40..199 to full range, near-black crops stay None.
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-m3 · Readers re-measured after S4/S18, views_agree, R7 line order
- views_agree keeps the lowest-threshold check only (n-or-0 at 170/190/210 gave 38 correct / 11 none); score re-measured 49/49 correct, panel sp/price/power level not worse, so sp._undim stays shared. power_visit now reports SP unreadable before an unknown keep; both lines are in the runbook table.
- pages: components/perception-score.md (updated), components/support-players.md (updated)

## 2026-10-30 · rdf03-r3-s16 · Numbers wider than the reading box read None
- sp._read checks a one-digit-pitch strip (OVERFLOW_U) right of the box, judged on the weakest channel, and returns None on a digit-sized blob there; before, SP 1234567 read 123456 and price 2500 read 250.
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-r4-s17 · read_price tolerates the box-cut edge of the last digit
- support.power_cards uv is ~3 px left of the button centre, so the last digit of 250 was cut and a 1 px column landed in the overflow strip (None). _digits_beyond now ignores blobs <= SLIVER_W (2) px wide; saved panel reads [250, 250, 250].
- pages: components/perception-score.md (updated)

## 2026-10-30 · rdf03-m4 · 4-5 digit power prices read; never buy on an unread price
- read_price finds the digit group inside PRICE_SEARCH_U instead of a fixed 3-digit box (4-5 digit case SYNTHETIC, no saved panel has a price >= 1000). power_visit no longer falls back to tracker.last_price: QA round 5 bought at a guessed 750 when the real price 1000 was unread and left SP below keep. Unread prices save capped panel_price_none_<t>.png frames for H3.
- pages: components/perception-score.md (updated), components/support-players.md (updated)

## 2026-11-01 · rdf04-t1 · LDPlayer profile
- Added rdom/profile.py (ld/gpg profiles, uv overrides, LD COOP_UV 0.497,0.823), config/recorder_ld.toml (measured chrome 16/80/16/8, place, adb keys), InputCfg backend/adb/serial, rdf04 fixtures and tools/check_ld_profile.py; LD detectors hold, invite-popup start_ready and COOP_UV v are OPEN H4 items.
- pages: components/profiles-ld.md (new)

## 2026-11-01 · rdf04-t2 · AdbInjector + --profile
- AdbInjector restored (dry-run default, no adb pipes, wm size fallback) on a shared _ActionBase; make_injector picks it by [input] backend; gear_bot/save_frame got --profile, save_frame --every/--minutes.
- pages: components/input-inject.md (updated), howto/run-bot.md (updated)

## 2026-11-01 · rdf04-t3 · Invite popup and joined-room detection
- Added perception/invite.py: template-only invite_popup and joined_room (threshold 0.80 mid-gap vs measured negatives), Hangul-only invite_name with fuzzy-cover name_matches; three new templates; not wired into a loop.
- pages: components/invite-detect.md (new), components/profiles-ld.md (updated)

## 2026-11-01 · rdf04-t4 · Joiner flow wait_and_accept
- Added input/coop_join.py: invite popup is handled before recover, accept needs 2 consecutive name matches, decline after 5 reads, joining phase skips recover; room_s overrun returns 'failed' (not 'room_timeout'); dry run returns 'stopped' after one decision. Not wired into a loop.
- pages: components/coop-join.md (new)

## 2026-11-01 · rdf04-t5 · Inviter flow invite_and_start
- Added input/friend_coop.invite_and_start: invites by name, re-invites after 3 s with neither 수락 대기중 nor start_ready, taps 협동 시작 once; start_friend_coop/open_room_and_wait left untouched (gated steps re-implemented on an injectable clock). Not wired into a loop.
- pages: components/coop-invite.md (new)

## 2026-11-01 · rdf04-t6 · Deck guard per role
- run_battle(expect=gear|support) refuses a wrong deck without hand-over; play(duo=True) marks the round record; detect_support_deck takes scales/box and gear_bot uses LD scales on the ld profile (negatives 0.487-0.636 on 7 LD gear frames).
- pages: components/support-bot-core.md (updated), components/perception-support.md (updated)

## 2026-11-01 · rdf04-t7 · Start check (preflight) + duo_check
- Added capture/preflight.check (window once, placed, uncovered, LD adb via temp-file wm size, two-window content overlap) with the spec reason texts, and tools/duo_check.py (two concurrent one-frame grab children). Not wired into a loop.
- pages: components/preflight.md (new)

## 2026-11-01 · rdf04-t8 · gear_loop roles, exit codes, records, tag
- gear_loop now has public/inviter/joiner roles, exit codes 0/3/crash, never deletes data/STOP, recover_step reports give-up so a stuck joiner fails rounds instead of relaunching forever.
- pages: components/gear-loop.md (new), components/coop-join.md (updated), components/safety-guards.md (updated)

## 2026-11-01 · rdf04-t9 · Supervisor duo/gear modes
- supervisor.py is a Supervisor class (injectable spawn/clock/sleep/notify/screenshot): duo inviter(ld)+joiner(gpg) or gear public child, crash counts per bot, guard stop or 5th crash writes STOP, waits for the other child, exits 1; writes bot_mode.json and (duo) room.json, removes pid/mode/STOP at exit; log per start `<stamp>_<bot>.log`.
- pages: components/supervisor.md (new), components/safety-guards.md (updated), howto/run-bot.md (updated)

## 2026-11-01 · rdf04-t10 · run_all duo by default, tagged tails
- run_all passes --mode duo (or gear with --gear-only), prints a header with names from config/duo.toml, follows per-bot logs tagged [기어]/[서폿]/[디코]; decision parts are pure functions and import is side-effect free.
- pages: components/run-all.md (new), components/supervisor.md (updated), howto/run-bot.md (updated)
