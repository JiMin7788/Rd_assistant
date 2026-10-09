"""친구와 하기 (play-with-friend coop) navigation + invite logic.

Flow (docs/02, user 2026-09-16):
  lobby -> 친구와 하기 -> 방 생성 -> 친구 초대 screen
  -> find the named friend and tap their invite button
  -> if the invite row does not show "수락 대기중", retry the invite after 3s
  -> once "협동 시작" activates, tap it.

Friend names are read with Tesseract OCR (Korean). Game fonts OCR imperfectly,
so matching is fuzzy. Implemented now; only regular coop is being tested, so the
invite path degrades gracefully when the friend is offline (name not found ->
retry loop).
"""
from __future__ import annotations
import difflib
import os
import time

import numpy as np
import cv2

from rdom.input.inject import (FRIEND_UV, CREATE_ROOM_UV, INVITE_FRIEND_UV,
                               START_COOP_UV, CLOSE_X_UV)

_TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSDATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "tessdata"))
# no quotes: tesseract appends /<lang>.traineddata to this literally
_CFG = f'--tessdata-dir {_TESSDATA} --psm 6'

# friend-select popup list ("초대할 친구를 선택하세요")
LIST_REGION = (0.08, 0.20, 0.92, 0.72)   # u0,v0,u1,v1
# the coop-room friend slot where "+ 친구 초대" turns into "<name> 수락 대기중"
SLOT_REGION = (0.14, 0.28, 0.86, 0.50)
WAITING_TEXT = "수락 대기중"


def _ocr_data(frame_rgb, region, scale=3, thresh=None):
    """OCR a normalized region. White-on-dark game text needs grayscale + upscale
    for Tesseract to see it (raw colour crops read empty). Returns
    [(text, u, v), ...] with box centers in normalized frame coords."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _TESS
    H, W = frame_rgb.shape[:2]
    u0, v0, u1, v1 = region
    x0, y0 = int(u0 * W), int(v0 * H)
    crop = frame_rgb[y0:int(v1 * H), x0:int(u1 * W)]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # Binarizing helps, but the right cut depends on the text: the friend names
    # are bright white on a purple panel, while "수락 대기중" is a dimmer blue.
    # A single cut of 150 read the names perfectly and ERASED the pending badge,
    # so the bot re-invited a friend it had already invited (2026-09-27) --
    # hence the per-caller threshold.
    if thresh is not None:
        _, gray = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    data = pytesseract.image_to_data(gray, lang="kor", config=_CFG,
                                     output_type=pytesseract.Output.DICT)
    out = []
    for i, txt in enumerate(data["text"]):
        if txt.strip():
            cx = x0 + (data["left"][i] + data["width"][i] / 2) / scale
            cy = y0 + (data["top"][i] + data["height"][i] / 2) / scale
            out.append((txt.strip(), cx / W, cy / H))
    return out


def _fuzzy(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _fuzzy_contains(haystack, needle):
    if needle.replace(" ", "") in haystack.replace(" ", ""):
        return True
    n = len(needle)
    return any(_fuzzy(haystack[i:i + n], needle) >= 0.6
               for i in range(max(1, len(haystack) - n + 1)))


def _name_cover(text, name):
    """Fraction of `name`'s characters that appear IN ORDER inside `text`.

    Plain similarity fails here: the game draws the name and its "접속 중" badge
    close together, so OCR hands back one row with the two interleaved
    ("대접번먹속중는자"). Measuring how much of the NAME survives, rather than how
    alike the two strings are, ignores whatever else landed in the row
    (2026-09-27: a real, listed friend was rejected 10 times in a row)."""
    sm = difflib.SequenceMatcher(None, text, name)
    return sum(b.size for b in sm.get_matching_blocks()) / max(1, len(name))


def _rows(tokens, vtol=0.012):
    """Group OCR tokens into rows (similar v), each concatenated left-to-right.
    Game text often comes back split per character, so rebuild the line."""
    rows = []
    for txt, u, v in sorted(tokens, key=lambda t: (round(t[2] / vtol), t[1])):
        if rows and abs(v - rows[-1][2]) <= vtol:
            rows[-1][0].append((u, txt))
            rows[-1][1] = sum(x for x, _ in rows[-1][0]) / len(rows[-1][0])
            rows[-1][2] = v
        else:
            rows.append([[(u, txt)], u, v])
    out = []
    for toks, _, v in rows:
        text = "".join(t for _, t in sorted(toks))
        out.append((text, v))
    return out


def find_friend_in_popup(frame_rgb, name, thresh=0.5):
    """In the friend-select popup, return the (u,v) to tap for `name`'s row, or
    None. Rebuilds rows from per-character OCR before matching."""
    key = name.replace(" ", "")
    for text, v in _rows(_ocr_data(frame_rgb, LIST_REGION, thresh=150)):
        t = text.replace(" ", "")
        if (_fuzzy(t, key) >= thresh or _name_cover(t, key) >= 0.6
                or (len(key) >= 3 and key[:3] in t)):
            return (0.5, v)     # tap the friend row (spans the popup width)
    return None


def slot_pending(frame_rgb):
    """True if the coop-room friend slot shows '수락 대기중' (invite sent)."""
    for th in (100, None):                       # dim blue text: soft cut, then raw
        joined = " ".join(t for t, _, _ in _ocr_data(frame_rgb, SLOT_REGION,
                                                     thresh=th))
        if _fuzzy_contains(joined, WAITING_TEXT):
            return True
    return False


def start_ready(frame_rgb):
    """True once the 협동 시작 button is active (turns yellow when the friend
    accepts). Colour-based, so it is robust to OCR flakiness -- measured:
    ~0.61 yellow when active vs ~0.00 while greyed/waiting."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.60 * H):int(0.69 * H), int(0.28 * W):int(0.68 * W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return ((h >= 18) & (h <= 35) & (s > 120) & (v > 150)).mean() > 0.30


def _wait_for(grab, pred, timeout=5.0, step=0.3):
    """Poll until pred(frame) holds; the frame that satisfied it, or None."""
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        f = grab.grab()
        if pred(f):
            return f
        time.sleep(step)
    return None


def start_friend_coop(grab, inj, name, retry_sec=3.0, max_retries=10, nav_wait=1.5):
    """Full 친구와 하기 flow (docs/02). Returns True if 협동 시작 was tapped.

      친구와 하기 -> 방 생성 -> coop room -> [친구 초대 -> pick `name`] retried
      until the friend slot shows 수락 대기중 -> wait for accept -> 협동 시작.

    Every tap is gated on the screen it is meant for. The blind version tapped
    친구와 하기 while a post-game lobby popup swallowed it, then kept tapping 친구
    초대 and the popup X on the bare LOBBY -- which are 난이도 선택 / 다이스 트리 --
    and bounced between those screens for nine "attempts" (2026-10-01). Now a
    screen that is not the expected one aborts the round with None (navigation
    broke -- the caller recovers with to_lobby() and stops the run if it keeps
    happening); False means only that the friend did not come.
    """
    from rdom.perception.board import (is_lobby, is_friend_menu, is_coop_room,
                                       has_popup_close)
    if not is_lobby(grab.grab()):
        print("not on the lobby -- abort round", flush=True)
        return None
    print("친구와 하기", flush=True)
    inj.tap(*FRIEND_UV)
    if _wait_for(grab, is_friend_menu) is None:
        print("친구와 하기 menu did not open -- abort round", flush=True)
        return None
    print("방 생성", flush=True)
    inj.tap(*CREATE_ROOM_UV)
    if _wait_for(grab, is_coop_room) is None:
        print("coop room did not open -- abort round", flush=True)
        return None

    invited = False
    for attempt in range(max_retries):
        f = grab.grab()
        if not is_coop_room(f):
            print("left the coop room -- abort round", flush=True)
            return None
        # An invite that is already out must NOT be re-sent: while the slot shows
        # 수락 대기중 the 친구 초대 button does nothing, so the retry tapped it, OCR'd
        # the ROOM instead of the friend list and reported the friend offline --
        # ten times, with the invite sitting there pending all along (2026-09-27).
        if slot_pending(f):
            print("수락 대기중 -- invite already pending", flush=True)
            invited = True
            break
        print(f"친구 초대 (attempt {attempt+1})", flush=True)
        inj.tap(*INVITE_FRIEND_UV)                           # open friend-select popup
        if _wait_for(grab, has_popup_close, timeout=4.0) is None:
            print("friend list did not open -- retry", flush=True)
            time.sleep(retry_sec)
            continue
        time.sleep(0.5)                                      # list rows settle
        who = None
        for _ in range(4):                               # OCR is per-frame flaky
            who = find_friend_in_popup(grab.grab(), name)
            if who:
                break
            time.sleep(0.5)
        if who:
            print(f"select {name} at {who}", flush=True)
            inj.tap(*who); time.sleep(nav_wait)              # invite -> back to room
            for _ in range(6):                               # badge needs a beat
                if slot_pending(grab.grab()):
                    invited = True
                    break
                time.sleep(0.5)
            if invited:
                print("수락 대기중 -- invite sent", flush=True)
                break
        else:
            print(f"{name} not online / not found -- retry in {retry_sec}s", flush=True)
            if has_popup_close(grab.grab()):                 # only if the list is up
                inj.tap(*CLOSE_X_UV)                         # close popup back to room
        time.sleep(retry_sec)                                # 친구초대 루프 재실행
    if not invited:
        print("gave up inviting after retries", flush=True)
        return False

    # friend accepts -> the 협동 시작 button turns active (yellow) -> tap it.
    # Use the button colour, not the absence of '수락 대기중', so a single flaky
    # OCR frame can't trigger a premature start.
    for _ in range(60):
        f = grab.grab()
        if start_ready(f):
            print("협동 시작", flush=True)
            inj.tap(*START_COOP_UV)
            return True
        if not is_coop_room(f):
            print("left the coop room while waiting -- abort round", flush=True)
            return None
        time.sleep(1.0)
    print("협동 시작 never activated", flush=True)
    return False


def open_room_and_wait(grab, inj, timeout=1800.0, nav_wait=1.5):
    """친구와 하기 -> 방 생성 -> NO invite: wait until someone joins (the 협동 시작
    button turns active) -> tap it. Returns True when tapped, False on timeout,
    None when navigation broke. Also returns True if a battle starts by itself."""
    from rdom.perception.board import is_lobby, is_friend_menu, is_coop_room, is_battle
    f0 = grab.grab()
    if is_coop_room(f0):
        print("already in an open coop room -- waiting there", flush=True)
    elif not is_lobby(f0):
        print("not on the lobby -- abort round", flush=True)
        return None
    else:
        print("친구와 하기", flush=True)
        inj.tap(*FRIEND_UV)
        if _wait_for(grab, is_friend_menu) is None:
            print("친구와 하기 menu did not open -- abort round", flush=True)
            return None
        print("방 생성", flush=True)
        inj.tap(*CREATE_ROOM_UV)
        if _wait_for(grab, is_coop_room) is None:
            print("coop room did not open -- abort round", flush=True)
            return None
    print(f"room open -- waiting up to {timeout/60:.0f} min for someone to join", flush=True)
    try:
        from rdom.perception.gear import read_room_code
        from rdom.notify.discord import send_code
        code = None
        for _ in range(4):
            code = read_room_code(grab.grab())
            if code: break
            time.sleep(0.5)
        print("room code:", code, flush=True)
        if code and code != getattr(open_room_and_wait, "_last_code", None):
            send_code(f"방 코드: **{code}**  ({time.strftime('%H:%M')})")
            open_room_and_wait._last_code = code
    except Exception as e:
        print("room code notify failed:", e, flush=True)
    t0 = time.monotonic(); last = t0; away = 0
    while time.monotonic() - t0 < timeout:
        f = grab.grab()
        if is_battle(f):
            print("battle started", flush=True)
            return True
        if start_ready(f):
            print(f"someone joined after {time.monotonic()-t0:.0f}s -- 협동 시작", flush=True)
            inj.tap(*START_COOP_UV)
            return True
        # one unrecognised frame (joiner animation, toast) aborted a 19-min wait
        # (2026-10-08): only give up after ~5 s off the room
        away = 0 if is_coop_room(f) else away + 1
        if away >= 5:
            print("left the coop room while waiting -- abort round", flush=True)
            return None
        if time.monotonic() - last > 60:
            print(f"  still waiting ({(time.monotonic()-t0)/60:.0f} min)", flush=True); last = time.monotonic()
        time.sleep(1.0)
    print("nobody joined", flush=True)
    return False
