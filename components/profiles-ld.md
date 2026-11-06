---
title: Capture profiles (LDPlayer / GPG) and the LD offline check
type: component
updated: 2026-11-06
sources: [rdf04-t1, rdf04-r1-s2, rdT06, rdT15]
---
# Capture profiles (LDPlayer / GPG) and the LD offline check

rdF04 first ran the gear bot on LDPlayer and the support bot on Google Play Games; since rdT06 LD is unused and the duo is a gear bot (`gpg`) and, since rdT15, a support bot (`gpg2`) on two Google Play Games windows (LD code is kept until a later removal task). `rdom.profile` names each one
(bot, Discord tag, recorder toml, UI overrides); `config/recorder_ld.toml` describes the LD window. Nothing
calls the profile module yet, and the adb input path does not exist yet (rdf04-t2).

## Profile module
- `Profile(name, bot, tag, config, ui)` is frozen. `PROFILES["ld"]` = gear, `[기어]`, `config/recorder_ld.toml`;
  `PROFILES["gpg"]` = gear, `[기어1]`, `config/recorder.toml` (title `^랜덤 다이스 2 - CumbersomeTutor145$` = 대변먹는자, inviter / public bot; swapped by rdT08, rdT06 had it the wrong way round); `PROFILES["gpg2"]` = support, `[서폿]` (rdT15; gear before), `config/recorder_gpg2.toml` (title `^랜덤 다이스 2 - CleanCardinal77$` = 배속봇, joiner, same chrome 132/72/0/0 and size 1384x2304 at y 2160, placed left of window 1 at x 1508 so they do not overlap). The `$`-anchored titles keep each regex from matching the other window or the `Google Play Games` launcher. `get(name)` raises KeyError listing known names.
- `uv(profile, key)` returns the profile's override, else the shared constant of that name in `rdom.input.inject`
  (measured on GPG). Only the LD profile has overrides: `COOP_UV = (0.497, 0.823)`, the pre-GPG LD value of
  commit `3a70f61^`.
- OPEN (H4): in old LD session lobby frames the green 협동 button spans v 0.699-0.803, so 0.823 lies below it
  and the shared 0.745 would also hit it. No current LD lobby frame exists; confirm on the live window.

## config/recorder_ld.toml
- `window_title_re = "^LDPlayer$"`; chrome left 16 / top 80 / right 16 / bottom 8 measured on the 1154x2082
  whole-window grabs, giving a 1122x1994 content (0.5627 vs 9:16 = 0.5625). `right` equals what
  `geometry.fit_chrome` derives anyway. Chrome is fixed config, never auto-detected.
- `[target.place]` x 1736, y 2200, 1154x2082 on DISPLAY2, left of the GPG window with no overlap.
- `[capture] monitor_index = 1` (DISPLAY2); `[input] backend = "adb"`, adb path and serial `127.0.0.1:5555`.
- UNVERIFIED until H4: that the client rect equals the grabbed window rect (invisible borders inside it).
- `InputCfg` gained `backend` (default `"postmessage"`), `adb`, `serial`; they are only parsed, so
  `config/recorder.toml` loads unchanged.

## Offline check: tools/check_ld_profile.py
Read-only; prints the 12 screen detectors, `read_speed`, `slot_pending`/`start_ready`, `gear.ui_state` and
`detect_deck` per PNG or per folder. `--sessions` cuts frames out of the old LD session videos into a fresh
tmp dir, never under `data/`. The module docstring holds the recorded run (6 fixtures + 22 session frames).
- `content_of(frame, cfg)` runs before the detectors and prints one info line per file. A frame exactly the
  `[target.place]` size (1154x2082) is a whole-window grab: it is cropped with `fit_chrome` + `Viewport(...).content`
  (what the bot does), because the detectors expect the content area only; on a window grab `room`/`modalX` read 0.
  Any other size is used as is (content frame). The line shows chrome insets L/T/R/B, content size, aspect vs
  9:16 and the % difference; over 1% it adds `NOT 9:16: window WxH would give 9:16`, which names the window size
  to use (needed when the window is too narrow for `fit_chrome` to give 9:16, as it clamps `right` to 0).
- The screen detectors written on LD hold on LD: lobby, friend menu, coop room, battle, result screen all read
  as expected on the session frames.
- Popup and joined-room detection now live in [invite-detect](invite-detect.md) (rdf04-t3).
- Known mismatches, all OPEN for H4, none fixed by an override: the invite popup reads
  `start_ready` True (its yellow 초대 수락 button sits in the 협동 시작 colour patch); an old 1.1.3 coop room
  reads `is_exit_dialog` True; a battle dimmed by a banner reads `is_battle` False.
- `gpg_joined_room` reads `is_coop_room` False; that is a GPG item, not an LD one.

## Fixtures
`tests/fixtures/rdf04/` holds six content-only crops (no title bar, so no Google account name; Hard Rule R5);
the README names each source. LD crops are 1122x1994, GPG crops 1244x2224.

## Evidence
- commit `8d88a7a` (branch task/rdf04-t1, not yet merged into this checkout, so paths are not lint-checked) — adds config/recorder_ld.toml (chrome measurement comment, place, monitor_index, adb keys, UNVERIFIED note), src/rdom/profile.py (Profile, PROFILES, get, uv, COOP_UV override and its OPEN comment) and the InputCfg backend/adb/serial fields in src/rdom/recorder/config.py.
- commit `1f2bcbb` (branch task/rdf04-r1-s2, not yet merged into this checkout, so paths are not lint-checked) — check_ld_profile.py content_of and main (window-grab crop, info line, NOT 9:16 hint); test_profile_ld.py tests test_check_ld_profile_crops_window_grab_and_reports_chrome and test_check_ld_profile_reports_window_size_for_off_aspect.
- commit `87f0696` (rdT06, branch task/rdT06, not yet merged into this checkout) — `src/rdom/profile.py` `PROFILES`, `config/recorder.toml` `window_title_re`, new config/recorder_gpg2.toml (title, place, chrome); tests/test_gpg_windows.py checks each regex matches exactly its own window.
- commit `8d88a7a` — tools/check_ld_profile.py docstring holds the run (expected vs read, mismatches, findings); tests/test_profile_ld.py asserts config loads, 9:16 content, profile lookups and fixture detector results; tests/fixtures/rdf04/README.md names each fixture's source.
