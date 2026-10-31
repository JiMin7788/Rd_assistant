"""게임 초대 (coop invite) popup, inviter name and joined-room detection.

Pure functions on an RGB content frame (no window chrome). Detection is template
matching only (TM_CCOEFF_NORMED via gear._best, multi-scale) -- no hue-band rules
(docs/07). The templates were cut from the GPG fixtures in tests/fixtures/rdf04;
the LD frames (9 % narrower) match them at scale 0.9.

Measured scores (best over UI_SCALES inside the search box, 2026-11-01):
  template      positives                                  highest negative
  invite_title  gpg_invite_popup 1.000, ld_invite_popup    0.608 (ld_host_* rooms; GPG rooms 0.592),
                0.943                                      0.604 data/support_frames/_check/lvbox_sup20261029_135038_panel_121.1.png
  invite_accept gpg_invite_popup 1.000, ld_invite_popup    0.440 (ld_host_joined_start_ready), 0.364
                0.974                                      data/support_runs/sup20261031_111332/end.png
  room_title    gpg_joined_room 1.000, gpg_host_invite_    0.565 data/support_frames/sup20261029_141449/884.6.png
                pending 1.000, ld_host_* 0.936             (popups: 0.443 gpg, 0.459 ld)
Negatives: the six rdF04 fixtures against the templates they are not, plus 63 frames
read from C:/dev/rdom/data by absolute path (20 support_runs/*/end.png result screens,
43 evenly spaced support_frames battle/panel frames; no lobby frames exist there beyond
the popup fixtures' own lobby). Thresholds sit mid-gap (0.80).
"""
from __future__ import annotations
import os

import cv2

from rdom.perception import gear
from rdom.perception.board import has_modal_x
from rdom.input.friend_coop import _ocr_data, _rows, _name_cover

_TPL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "assets", "templates"))

# search boxes (u0, v0, u1, v1) -- generous, the popup is centred
TITLE_BOX = (0.25, 0.14, 0.75, 0.24)
ACCEPT_BOX = (0.10, 0.58, 0.90, 0.76)
ROOM_TITLE_BOX = (0.25, 0.17, 0.75, 0.25)   # the lower 협동 같이하기 of the popup starts at v .26
NAME_BOX = (0.30, 0.29, 0.80, 0.40)          # banner name of the inviter

# popup X: fixed in the modal frame (GPG u .865 v .171, LD u .869 v .172)
CLOSE_UV = (0.867, 0.171)

# AI-NOTE: thresholds sit between the measured positive and highest negative.
TITLE_MIN = 0.80         # positive 0.943 (LD), highest negative 0.608
ACCEPT_MIN = 0.80        # positive 0.974 (LD), highest negative 0.440
ROOM_TITLE_MIN = 0.80    # positive 0.936 (LD host), highest negative 0.565

# AI-NOTE: a false accept puts the bot in a stranger's room, so a fuzzy cover
# below this is rejected (OCR of the game font interleaves badge text, hence
# cover and not plain similarity).
NAME_COVER_MIN = 0.8

_cache = {}


def _tpl(name):
    if name not in _cache:
        im = cv2.imread(os.path.join(_TPL, name))
        _cache[name] = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    return _cache[name]


def _find(f, name, box):
    """(score, (u, v) centre of the best match) of template `name` inside `box`."""
    H, W = f.shape[:2]
    x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
    sc, (x, y), (tw, th) = gear._best(f[y0:y1, x0:x1], _tpl(name))
    return sc, ((x0 + x + tw / 2) / W, (y0 + y + th / 2) / H)


def scores(f):
    """Raw template scores, for threshold measurement."""
    return {"title": _find(f, "invite_title.png", TITLE_BOX)[0],
            "accept": _find(f, "invite_accept.png", ACCEPT_BOX)[0],
            "room": _find(f, "room_title.png", ROOM_TITLE_BOX)[0]}


def invite_popup(f):
    """{'accept_uv', 'close_uv'} if the 게임 초대 popup is up, else None."""
    st, _ = _find(f, "invite_title.png", TITLE_BOX)
    if st < TITLE_MIN:
        return None
    sa, accept_uv = _find(f, "invite_accept.png", ACCEPT_BOX)
    if sa < ACCEPT_MIN:
        return None
    return {"accept_uv": accept_uv, "close_uv": CLOSE_UV}


def invite_name(f):
    """Inviter name read from the banner (Hangul only), '' if unreadable."""
    rows = _rows(_ocr_data(f, NAME_BOX, thresh=150))
    # AI-NOTE: keep Hangul syllables only; the banner artwork next to the name
    # makes Tesseract emit stray punctuation/digits ('~/1대변먹는자').
    return "".join(c for t, _ in rows for c in t if "가" <= c <= "힣")


def name_matches(text, host):
    t, h = text.replace(" ", ""), host.replace(" ", "")
    if not h or not t:
        return False
    return t == h or _name_cover(t, h) >= NAME_COVER_MIN


def joined_room(f):
    """True in the 협동 같이하기 room (host or joiner view)."""
    if not has_modal_x(f):
        return False
    return _find(f, "room_title.png", ROOM_TITLE_BOX)[0] >= ROOM_TITLE_MIN
