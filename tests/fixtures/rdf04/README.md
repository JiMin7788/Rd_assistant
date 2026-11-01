# rdF04 fixtures (content only: no window title bar, no emulator chrome — Hard Rule R5)

Sources are in `C:/dev/_hub/features/rdF04/screens`, taken 2026-11-01.

- `gpg_host_invite_pending.png` — 1244x2224, copy of `gpg_host_invite_pending_20261101_062740.png` (already content, save_frame).
- `gpg_invite_popup.png` — 1244x2224, `gpg_invite_popup_062902.png` (1384x2304 window grab) cropped x 140-1384, y 80-2304 (GPG chrome left 132 + 8 px border, top 72 + 8 px border).
- `gpg_joined_room.png` — 1244x2224, `gpg_joined_room_062932.png` (1384x2304) cropped x 140-1384, y 80-2304.
- `ld_invite_popup.png` — 1122x1994, `ld_invite_popup_20261101_0627.png` (1154x2082 window grab) cropped x 16-1138, y 80-2074 (config/recorder_ld.toml chrome).
- `ld_host_pending.png` — 1122x1994, `ld_host_pending_062902.png` (1154x2082) cropped x 16-1138, y 80-2074.
- `ld_host_joined_start_ready.png` — 1122x1994, `ld_host_joined_start_ready_062948.png` (1154x2082) cropped x 16-1138, y 80-2074.

The LD crop is exactly what fit_chrome(client 1154x2082, chrome 16/80/16/8) yields (1122x1994, 9:16 within 0.04 %). It assumes the grabbed window rect equals the client rect (unverified until H4).
