"""Battle SP (white digits on a dark pill above the 소환 button) and the summon cost (digits on the 소환 button),
read with the template digit reader. Exact or nothing, like perception.score: None whenever the templates are missing,
the crop is empty, the reader is unsure or the number is out of range.
"""
from __future__ import annotations
import cv2

from rdom.perception import digits

# (u0, v0, u1, v1) in content-normalised coordinates (u relative to round(h*9/16), v to h), digits only.
# Measured on H1/H2 battle frames sup20261029_135038/548.1.png, sup20261029_145953/912.9.png and
# sup20261030_063914/183.4.png (1244x2224), ink-column projections checked on 20 more frames of five games.
# SP: the 'Ø' icon sits at a fixed place (u 0.412-0.442) and the digits (up to 6) fill u 0.451-0.584, v 0.793-0.809,
# so u0 = 0.446 leaves the icon outside. A '+N' kill popup (cyan) can overlap the digits; such reads must be None.
SP_BOX = (0.446, 0.790, 0.600, 0.813)
# Cost: the 'Ø' icon moves with the number of digits (right edge u 0.484 for 2 digits, 0.472 for 3, 0.461 for 4) and the
# first digit starts at u 0.499 / 0.483 / 0.476. u0 = 0.4745 keeps the icon outside for 3-4 digit costs; for a 2-digit
# cost (10..90, first summons only) a sliver of the icon is inside and the reader refuses (None).
COST_BOX = (0.4745, 0.876, 0.575, 0.897)
MAX_SP = 9_999_999
MAX_COST = 99_999
# Room-template fallback (tools/build_digit_templates.py sp cost): none. All ten digits 0-9 have samples in
# data/digits/sp (>= 24 per digit) and data/digits/cost (>= 7 per digit), so no digit fell back to the room templates.


def read_crop(gray, kind):
    """Number in an already cut grey crop with the digits_<kind>.npz templates, or None (missing npz, empty, unsure)."""
    try:
        if gray is None or gray.ndim != 2 or gray.shape[0] < 4 or gray.shape[1] < 4:
            return None
        r = digits.read_number(gray, kind)
    except (OSError, cv2.error, ValueError):                 # no digits_<kind>.npz yet / degenerate crop
        return None
    return None if r is None else int(r)


def _read(frame_rgb, box, kind, lo, hi):
    if frame_rgb is None or frame_rgb.ndim < 2 or frame_rgb.shape[0] < 2:
        return None
    h = frame_rgb.shape[0]; W = round(h * 9 / 16)           # true 9:16 content width, as gear._content_w
    u0, v0, u1, v1 = box
    crop = frame_rgb[int(v0 * h):int(v1 * h), int(u0 * W):int(u1 * W)]
    if crop.size == 0:
        return None
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)   # AI-NOTE: a 2-D grey frame must give None, not a cv2 error
    r = read_crop(gray, kind)
    return r if r is not None and lo <= r <= hi else None


def read_sp(frame_rgb):
    """SP above 소환 as int in 0..9_999_999, or None."""
    return _read(frame_rgb, SP_BOX, "sp", 0, MAX_SP)


def read_summon_cost(frame_rgb):
    """Summon cost on the 소환 button as int in 1..99_999, or None."""
    return _read(frame_rgb, COST_BOX, "cost", 1, MAX_COST)
