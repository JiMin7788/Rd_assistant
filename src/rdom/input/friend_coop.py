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
import glob
import os
import time

import numpy as np
import cv2

from rdom.input.inject import (FRIEND_UV, CREATE_ROOM_UV, INVITE_FRIEND_UV,
                               START_COOP_UV, CLOSE_X_UV, MODAL_X_UV)

_TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSDATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "tessdata"))
# no quotes: tesseract appends /<lang>.traineddata to this literally
_CFG = f'--tessdata-dir {_TESSDATA} --psm 6'

# friend-select popup list ("초대할 친구를 선택하세요")
LIST_REGION = (0.08, 0.20, 0.92, 0.72)   # u0,v0,u1,v1
# the coop-room friend slot where "+ 친구 초대" turns into "<name> 수락 대기중"
SLOT_REGION = (0.14, 0.28, 0.86, 0.50)
WAITING_TEXT = "수락 대기중"
FRIEND_THRESHOLDS = (150, 120, 180, None)   # None = grayscale without binarizing
# AI-NOTE: failed friend-list / 로비로 가기 frames land here so a live failure can be measured;
# DEBUG_KEEP files are kept per prefix. Tests monkeypatch COOP_DEBUG_DIR (never write the real data/).
COOP_DEBUG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "coop_debug"))
DEBUG_KEEP = 20


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
    None. Rebuilds rows from per-character OCR before matching, at several thresholds
    (the live 2026-11-05 list was not read at 150 alone); any row of any read may match.
    When nothing matches the popup frame is saved to data/coop_debug/ for measuring."""
    key = name.replace(" ", "")
    for th in FRIEND_THRESHOLDS:
        for text, v in _rows(_ocr_data(frame_rgb, LIST_REGION, thresh=th)):
            t = text.replace(" ", "")
            if (_fuzzy(t, key) >= thresh or _name_cover(t, key) >= 0.6
                    or (len(key) >= 3 and key[:3] in t)):
                return (0.5, v)     # tap the friend row (spans the popup width)
    path = save_debug_frame("friend_list", frame_rgb)
    if path:
        print(f"friend list saved: {path}", flush=True)
    return None


def save_debug_frame(prefix, frame_rgb, keep=DEBUG_KEEP):
    """Save `frame_rgb` as COOP_DEBUG_DIR/<prefix>_<timestamp>.png, keeping the newest `keep`
    files of that prefix. Returns the path, or None when it could not be written."""
    try:
        os.makedirs(COOP_DEBUG_DIR, exist_ok=True)
        path = os.path.join(COOP_DEBUG_DIR, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        if not cv2.imwrite(path, cv2.cvtColor(np.asarray(frame_rgb), cv2.COLOR_RGB2BGR)):
            return None
        old = sorted(glob.glob(os.path.join(COOP_DEBUG_DIR, f"{prefix}_*.png")), key=os.path.getmtime)
        for p in old[:-keep]:
            os.remove(p)
        return path
    except Exception as e:                    # a debug dump must never break the bot
        print(f"debug frame not saved: {e}", flush=True)
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


TICK_S = 0.5            # duo wait-loop period; should_stop is checked every tick (<= 2 s required)
EXPIRED_S = 3.0         # neither 수락 대기중 nor start_ready for this long -> the invite ran out
ROOM_GONE_S = 5.0       # not in the coop room for this long -> navigation broke


def _uv_map(uv):
    m = {"FRIEND": FRIEND_UV, "CREATE_ROOM": CREATE_ROOM_UV, "INVITE_FRIEND": INVITE_FRIEND_UV,
         "START_COOP": START_COOP_UV, "CLOSE_X": CLOSE_X_UV, "MODAL_X": MODAL_X_UV}
    m.update(uv or {})
    return m


def _wait_until(grab, pred, timeout, now, sleep, step=0.3):
    """_wait_for on an injectable clock: the frame that satisfied pred, or None."""
    t_end = now() + timeout
    while now() < t_end:
        f = grab.grab()
        if pred(f):
            return f
        sleep(step)
    return None


def invite_and_start(grab, inj, name, wait_s=300, should_stop=lambda: None, uv=None,
                     now=time.monotonic, sleep=time.sleep):
    """Duo lobby step: 친구와 하기 -> 방 생성 -> invite `name` -> tap 협동 시작 once they are in.

    -> True (start tapped) | False (wait_s over) | None (navigation broke) |
       'stopped' / 'paused' (should_stop() said 'stop' / 'pause'; the room is left with MODAL_X).
    The invite is kept alive: when the slot shows neither 수락 대기중 nor a ready start for
    EXPIRED_S the invite has expired and is sent again. No room code is read or published.
    """
    from rdom.perception.board import (is_lobby, is_friend_menu, is_coop_room,
                                       has_popup_close)
    uvs = _uv_map(uv)

    def tap(key):
        inj.tap(*uvs[key])

    # AI-NOTE: gear_loop.recover_step ends on a coop room and on the 친구와 하기 menu (the public
    # role continues from both), so the inviter must too -- else a crash/restart while waiting in
    # the room fails every following round at once. Same branching as open_room_and_wait.
    f0 = grab.grab()
    if is_coop_room(f0):
        print("already in an open coop room -- inviting there", flush=True)
    else:
        if is_friend_menu(f0):
            print("친구와 하기 menu already open -- 방 생성", flush=True)
        elif is_lobby(f0):
            print("친구와 하기", flush=True)
            tap("FRIEND")
            if _wait_until(grab, is_friend_menu, 5.0, now, sleep) is None:
                print("친구와 하기 menu did not open -- abort round", flush=True)
                return None
            print("방 생성", flush=True)
        else:
            print("not on the lobby -- abort round", flush=True)
            return None
        tap("CREATE_ROOM")
        if _wait_until(grab, is_coop_room, 5.0, now, sleep) is None:
            print("coop room did not open -- abort round", flush=True)
            return None

    def invite():
        """One 친구 초대 -> pick `name`; True if the friend row was tapped."""
        print("친구 초대", flush=True)
        tap("INVITE_FRIEND")
        if _wait_until(grab, has_popup_close, 4.0, now, sleep) is None:
            print("friend list did not open", flush=True)
            return False
        sleep(0.5)                                           # list rows settle
        who = None
        for _ in range(4):                                   # OCR is per-frame flaky
            who = find_friend_in_popup(grab.grab(), name)
            if who:
                break
            sleep(0.5)
        if not who:
            print(f"{name} not online / not found", flush=True)
            if has_popup_close(grab.grab()):
                tap("CLOSE_X")
            return False
        print(f"select {name} at {who}", flush=True)
        inj.tap(*who)
        sleep(1.5)                                           # invite -> back to room
        return True

    t0 = now()
    invited = False
    # AI-NOTE: start_friend_coop is left untouched on purpose (its 60 s wait and retry caps are
    # live-tested); the duo step re-implements the gated steps on an injectable clock.
    idle_since = t0          # since when the slot shows neither pending nor ready
    away_since = None
    while True:
        stop = should_stop()
        if stop in ("stop", "pause"):
            tap("MODAL_X")
            return "stopped" if stop == "stop" else "paused"
        t = now()
        if t - t0 >= wait_s:
            print("invite wait over -- leaving the room", flush=True)
            tap("MODAL_X")
            return False
        f = grab.grab()
        if start_ready(f):
            print("협동 시작", flush=True)
            tap("START_COOP")
            return True
        if not is_coop_room(f):
            away_since = t if away_since is None else away_since
            if t - away_since >= ROOM_GONE_S:
                print("left the coop room while waiting -- abort round", flush=True)
                return None
            sleep(TICK_S)
            continue
        away_since = None
        if slot_pending(f):
            idle_since = None
        else:
            idle_since = t if idle_since is None else idle_since
            if not invited or t - idle_since >= EXPIRED_S:
                if invited:
                    print("invite expired -- inviting again", flush=True)
                if invite():
                    invited = True
                else:
                    sleep(EXPIRED_S)                         # same pause as start_friend_coop's retry
                idle_since = now()
                continue
        sleep(TICK_S)


def open_room_and_wait(grab, inj, timeout=1800.0, nav_wait=1.5):
    """친구와 하기 -> 방 생성 -> NO invite: wait until someone joins (the 협동 시작
    button turns active) -> tap it. Returns True when tapped, False on timeout,
    None when navigation broke. Also returns True if a battle starts by itself."""
    from rdom.perception.board import is_lobby, is_friend_menu, is_coop_room, is_battle
    f0 = grab.grab()
    if is_coop_room(f0):
        print("already in an open coop room -- waiting there", flush=True)
    elif is_friend_menu(f0):
        # 협동 같이하기 menu left open (친구와 하기 tapped, 방 생성 not) -- BACK does
        # not close it, so the round used to fail 3x and stop (2026-10-10)
        print("친구와 하기 menu already open -- 방 생성", flush=True)
        inj.tap(*CREATE_ROOM_UV)
        if _wait_for(grab, is_coop_room) is None:
            print("coop room did not open -- abort round", flush=True)
            return None
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
        from rdom.notify.discord import send_room_code
        from rdom.notify.room_state import write_room, bot_alive
        # send only a code read identically on 3 consecutive frames: a wrong code is worse than none
        code = None; prev = None; streak = 0
        for _ in range(12):
            c = read_room_code(grab.grab())
            streak = streak + 1 if c and c == prev else (1 if c else 0); prev = c
            if streak >= 3:
                code = c; break
            time.sleep(0.3)
        print("room code:", code, flush=True)
        write_room(code, "waiting")
        # the Discord bot hands the code out (public card or reservation DM) while it
        # runs; post it ourselves only as a fallback when the bot is down
        if code and not bot_alive() and code != getattr(open_room_and_wait, "_last_code", None):
            send_room_code(code)
            open_room_and_wait._last_code = code
    except Exception as e:
        print("room code notify failed:", e, flush=True)
    t0 = time.monotonic(); last = t0; away = 0
    while time.monotonic() - t0 < timeout:
        f = grab.grab()
        if is_battle(f):
            print("battle started", flush=True)
            _room_state("playing")
            return True
        if start_ready(f):
            print(f"someone joined after {time.monotonic()-t0:.0f}s -- 협동 시작", flush=True)
            inj.tap(*START_COOP_UV)
            _room_state("playing")
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


def _room_state(state):
    try:
        from rdom.notify.room_state import read_room, write_room
        write_room(read_room().get("code"), state)
    except Exception as e:
        print("room state failed:", e, flush=True)
