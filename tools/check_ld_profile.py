"""Offline check: which screen detectors hold on LDPlayer content frames (rdF04 t1).

    python tools/check_ld_profile.py tests/fixtures/rdf04            # a folder of PNGs
    python tools/check_ld_profile.py a.png b.png                     # or a list of PNGs
    python tools/check_ld_profile.py --sessions [--step 90] [--max 40]

Prints, per frame, board.is_lobby / has_popup_close / has_modal_x / is_friend_menu /
is_coop_room / is_exit_dialog / is_battle / is_game_over, read_speed,
friend_coop.slot_pending / start_ready, gear.ui_state (the on-flags) and gear.detect_deck.
Read-only: it never injects input and never writes under data/. ``--sessions`` cuts frames
out of the LD session videos under C:/dev/rdom/data/sessions/2026-10-0* into a fresh
tmp dir (printed at the end; delete it yourself).

Run of 2026-11-01 (worktree rdf04-t1; expected = the screen class judged by eye from the frame)
=============================================================================================
Fixtures (tests/fixtures/rdf04, LD 1122x1994 / GPG 1244x2224), expected -> read:
  ld_host_pending            room=1 pending=1 ready=0 modalX=1, rest 0   -> same (OK)
  ld_host_joined_start_ready room=1 ready=1 pending=0 modalX=1, rest 0   -> same (OK)
  ld_invite_popup            lobby=0 room=0 ready=0 (invite popup)       -> lobby=0 room=0 ready=1 (MISMATCH)
  gpg_invite_popup           lobby=0 room=0 ready=0                      -> lobby=0 room=0 ready=1 (MISMATCH)
  gpg_host_invite_pending    room=1 pending=1 ready=0                    -> same (OK)
  gpg_joined_room            room=1 ready=1                              -> room=0 ready=0 (GPG, not an LD item)
  battle/speed/deck/ui_state/exit/over = 0 / None / None / [] on all six (OK: none is a battle).
  The invite popup's yellow 초대 수락 button sits in the 협동 시작 colour patch, so start_ready
  reads True there: OPEN H4 item, handled by rdf04-t3 (invite popup detection), no override here.

Session frames (C:/dev/rdom/data/sessions/2026-10-0*, LD 10-07..10-09; 22 frames, cut into a
tmp dir with --sessions --step 100 plus five found by a detector scan (friend, over, exit rows)):
  screen        frame (session, s)                  expected (others 0)        read
  lobby         2214_15c8 0, 2312_1ec2 0, 0027_33ad 0,
                1727_e5ac 0, 0915_c6ed 0            lobby=1                    lobby=1 x5 (OK)
  friend menu   0915_c6ed 5, 2312_1ec2 5            friend=1 modalX=1          same x2 (OK)
  coop room     0915_c6ed 100, 1023_22bf 100,
                2354_72bb 100                       room=1 modalX=1 ready=0    same x3 (OK)
  coop room     1820_28fb 0 (yellow 협동 시작)       room=1 ready=1 exit=0      room=1 ready=1 exit=1 (MISMATCH)
  battle        1951_00f2 100, 2214_15c8 100,
                2354_72bb 200, 1356_dd21 0,
                2050_e3b6 100                       battle=1 deck=doom speed    battle=1 deck=doom speed 2.0/1.0/2.0/2.0/1.5 (OK)
  battle+hunt   1356_dd21 100                       battle=1 ready=0           battle=1 ready=1 (harmless: only used behind is_coop_room)
  dimmed battle 1820_28fb 300 (banner over it)      battle=1                   battle=0 (MISMATCH)
  power panel   2214_15c8 500                       battle=0 power_panel       battle=0 ui=[power_panel] (OK)
  result screen 1820_28fb seg1 545 and 560          over=1                     over=1 x2 (OK)
  popup + X     1951_00f2 0                         popupX=1 lobby=0           same (OK)
Speed: read as a float in every full battle frame, None elsewhere. Not checked against the real button.

Findings
- The 12 screen detectors hold on the LD session frames and on the current LD fixtures; every
  mismatch on a current LD fixture is the invite popup (start_ready=1), an OPEN H4 item for
  rdf04-t3. The two session mismatches (old 1.1.3 room with exit=1; dimmed battle) are OPEN H4 items.
- Tap targets: on ld_host_pending/ld_host_joined_start_ready, MODAL_X_UV, START_COOP_UV and
  INVITE_FRIEND_UV land on the red X, the 협동 시작 button and the friend slot (tests/test_profile_ld.py).
- profile.py overrides COOP_UV = (0.497, 0.823) (pre-GPG LD value, commit 3a70f61^). OPEN H4: in the old
  LD lobby frames above the green 협동 button spans v 0.699-0.803 (centre 0.751), so the shared
  GPG value (0.50, 0.745) also hits it and 0.823 lies below it; no current LD lobby frame exists.
  Confirm on the live LD window (H4) which value is right.
"""
from __future__ import annotations

import argparse
import glob
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdom.perception import board, gear  # noqa: E402
from rdom.input import friend_coop  # noqa: E402
from rdom.recorder.config import load_config  # noqa: E402
from rdom.recorder.geometry import GAME_ASPECT, Rect, Viewport, fit_chrome  # noqa: E402

LD_CONFIG = ROOT / "config" / "recorder_ld.toml"
SESSIONS = "C:/dev/rdom/data/sessions/2026-10-0*"
COLS = ("lobby", "popupX", "modalX", "friend", "room", "exit", "battle", "over",
        "speed", "pending", "ready", "deck")


def read_frame(path):
    bgr = cv2.imread(str(path))
    return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def content_of(frame, cfg):
    """(content frame, report line). A frame the size of the LD window is a whole-window grab
    and is cropped with the configured chrome; any other size is taken as a content frame."""
    # AI-NOTE: the detectors expect the content area only (the bot crops by
    # Viewport(client, fit_chrome(client, chrome)).content), so a window grab must be cropped
    # here or room/modalX read 0 on the tab bar and frame offsets.
    h, w = frame.shape[:2]
    pw, ph = cfg.target.place[2:]
    if (w, h) != (pw, ph):
        return frame, f"content frame {w}x{h} aspect {w / h:.4f} (not a {pw}x{ph} window grab, used as is)"
    client = Rect(0, 0, w, h)
    ch = fit_chrome(client, cfg.target.chrome)
    c = Viewport(client, ch).content
    aspect = c.width / c.height
    diff = abs(aspect / GAME_ASPECT - 1) * 100
    line = (f"window {w}x{h} chrome L{ch.left} T{ch.top} R{ch.right} B{ch.bottom} "
            f"content {c.width}x{c.height} aspect {aspect:.4f} vs 9:16 {GAME_ASPECT:.4f} "
            f"({diff:.2f}%)")
    if diff > 1.0:
        want_w = round((h - ch.top - ch.bottom) * GAME_ASPECT) + ch.left + cfg.target.chrome.right
        line += f" NOT 9:16: window {want_w}x{h} would give 9:16"
    return frame[c.top:c.bottom, c.left:c.right], line


def run_detectors(frame):
    """Every detector the gear bot's screen logic uses, as one dict (None = raised)."""
    def safe(fn):
        try:
            return fn(frame)
        except Exception:  # noqa: BLE001 -- a detector that raises is a finding, not a crash
            return None
    ui = safe(gear.ui_state)
    return {
        "lobby": safe(board.is_lobby), "popupX": safe(board.has_popup_close),
        "modalX": safe(board.has_modal_x), "friend": safe(board.is_friend_menu),
        "room": safe(board.is_coop_room), "exit": safe(board.is_exit_dialog),
        "battle": safe(board.is_battle), "over": safe(board.is_game_over),
        "speed": safe(board.read_speed),
        "pending": safe(friend_coop.slot_pending), "ready": safe(friend_coop.start_ready),
        "ui": None if ui is None else sorted(k for k, v in ui.items()
                                              if k != "scores" and v),
        "deck": safe(gear.detect_deck),
    }


def format_row(name, r):
    flags = " ".join(f"{c}={int(r[c]) if isinstance(r[c], (bool, np.bool_)) else r[c]}"
                     for c in COLS)
    return f"{name}: {flags} ui={r['ui']}"


def extract_session_frames(out_dir, step_sec=90.0, limit=40):
    """Cut one frame every `step_sec` from each LD session video into out_dir."""
    saved = []
    for vid in sorted(glob.glob(SESSIONS + "/video/seg_00000.mp4")):
        cap = cv2.VideoCapture(vid)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sess = Path(vid).parents[1].name
        for i in range(0, n, max(1, int(step_sec * fps))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, bgr = cap.read()
            if not ok:
                continue
            p = Path(out_dir) / f"{sess}_{i // int(fps):05d}s.png"
            cv2.imwrite(str(p), bgr)
            saved.append(p)
            if len(saved) >= limit:
                cap.release()
                return saved
        cap.release()
    return saved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="PNG files or folders of PNGs")
    ap.add_argument("--sessions", action="store_true", help="extract frames from the LD session videos")
    ap.add_argument("--step", type=float, default=90.0, help="seconds between session frames")
    ap.add_argument("--max", type=int, default=40, help="max session frames")
    a = ap.parse_args(argv)
    files = []
    for p in a.paths:
        pp = Path(p)
        files += sorted(pp.glob("*.png")) if pp.is_dir() else [pp]
    tmp = None
    if a.sessions:
        tmp = tempfile.mkdtemp(prefix="ld_sessions_")
        files += extract_session_frames(tmp, a.step, a.max)
    cfg = load_config(LD_CONFIG)
    for f in files:
        fr = read_frame(f)
        if fr is None:
            print(f"{f.name}: unreadable")
            continue
        fr, info = content_of(fr, cfg)
        print(f"{f.name}: {info}")
        print(format_row(f.name, run_detectors(fr)))
    if tmp:
        print(f"session frames in {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
