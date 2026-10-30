"""Battle SP (white digits on a dark pill above the 소환 button) and the summon cost (digits on the 소환 button),
read with the template digit reader. Exact or nothing, like perception.score: None whenever the templates are missing,
the crop is empty, the reader is unsure or the number is out of range.
"""
from __future__ import annotations
import math
import cv2
import numpy as np

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
MAX_PRICE = 999_999
# Room-template fallback (tools/build_digit_templates.py sp cost): none. All ten digits 0-9 have samples in
# data/digits/sp (>= 24 per digit) and data/digits/cost (>= 7 per digit), so no digit fell back to the room templates.

# Open power panel (rdf03-t4), measured on the six saved panel frames sup20261029_{135038,141449,143137,145953,152652}/
# panel_*.png and sup20261030_060122/panel_140.0.png (1244x2224, content width 1251).
# Panel SP: dark pill at the top centre of the panel, 'Ø' icon at x 500-542, digits left-aligned from x 586 (u 0.468) to
# about x 723 for 5 digits, y 1725-1765; the pill ends at x 777. A cyan '+30' kill popup lands on the middle digits
# (4 of the 6 frames); such reads must be None, never a wrong number.
PANEL_SP_BOX = (0.4636, 0.7734, 0.6155, 0.7959)
# Price: offsets (du0, dv0, du1, dv1) from a buy-button centre (gear.power_buttons / support.power_cards). The 'Ø' icon
# sits left of the digits (x 111-147 with the button centre at x 162); du0 starts at x 150, right of its diagonal spike.
# Digits '250' / '500' fill x 151-220, y 2084-2114 (centre y 2092). Wider prices are on no saved frame.
PRICE_BOX = (-0.0096, -0.0045, 0.0496, 0.0108)
# Room-template fallback (tools/build_digit_templates.py panelsp price powerlv): the six frames only show panel SP
# 59050 / 14510 / 11530 readable by eye (the other three have a '+30' popup over the digits), prices 250 / 500 and levels
# 1 / 2. So digits_panelsp.npz has samples for 0 1 3 4 5 9 (2 6 7 8 fall back to the room templates), digits_price.npz
# for 0 2 5 and digits_powerlv.npz for 1 2 only; every other digit is a room template (same game font). H3 will save
# more panel frames for a recalibration.


def read_crop(gray, kind):
    """Number in an already cut grey crop with the digits_<kind>.npz templates, or None (missing npz, empty, unsure)."""
    try:
        if gray is None or gray.ndim != 2 or gray.shape[0] < 4 or gray.shape[1] < 4:
            return None
        r = digits.read_number(gray, kind)
    except (OSError, cv2.error, ValueError):                 # no digits_<kind>.npz yet / degenerate crop
        return None
    return None if r is None else int(r)


DIM_PEAK = (40, 200)                                         # a crop whose brightest pixel lies in this range is a dimmed one


OVERFLOW_U = 0.022                                           # strip right of a box checked for digits the box cannot hold (one digit pitch; a longer one reaches the pale streak on skin right of the pill)


def _undim(gray, peak=None):
    """Stretch a dimmed crop to full range (`peak`: the brightest pixel of the digit box, default this crop's own).
    AI-NOTE: a dice-info panel / popup dims the whole battle (white digits peak at ~70 instead of 255), so the fixed
    170+ binarisation of digits.glyphs saw nothing and SP / cost read None. Clean crops peak at 255 and pass unchanged;
    below DIM_PEAK[0] nothing digit-like is there, so noise is not amplified."""
    peak = int(gray.max()) if peak is None else peak
    if not DIM_PEAK[0] <= peak < DIM_PEAK[1]:
        return gray
    return np.ascontiguousarray(np.minimum(gray.astype(np.float32) * (255.0 / peak), 255).astype(np.uint8))


def _digits_beyond(strip):
    """True if the grey strip right of the digit box holds a digit-sized bright blob. A blob as tall as the strip (the
    light sand behind the pill, a button edge) is no digit: same height window as digits.glyphs, but not fatal."""
    if strip.size == 0:
        return False
    h = strip.shape[0]
    _, b = cv2.threshold(strip, 170, 255, cv2.THRESH_BINARY)
    n, _, st, _ = cv2.connectedComponentsWithStats(b)
    return any(st[i][4] >= 0.004 * b.size and 0.30 * h <= st[i][3] <= 0.95 * h for i in range(1, n))


def _read(frame_rgb, box, kind, lo, hi, min_channel=False):
    if frame_rgb is None or frame_rgb.ndim < 2 or frame_rgb.shape[0] < 2:
        return None
    h = frame_rgb.shape[0]; W = round(h * 9 / 16)           # true 9:16 content width, as gear._content_w
    u0, v0, u1, v1 = box
    if min(u0, v0) < 0:                                      # AI-NOTE: a negative slice start would wrap to the far side of the frame
        return None
    x0, x1 = int(u0 * W), int(u1 * W)
    crop = frame_rgb[int(v0 * h):int(v1 * h), x0:int((u1 + OVERFLOW_U) * W)]   # the box plus the strip right of it
    if crop.size == 0 or x1 <= x0:
        return None
    if crop.ndim == 2:                                       # AI-NOTE: a 2-D grey frame must give None, not a cv2 error
        gray = crop
    elif min_channel:                                        # AI-NOTE: white digits on the green button: its grey (~180) sits next to the 170 threshold, the weakest channel (~90) does not
        gray = np.ascontiguousarray(crop[..., :3].min(axis=2))
    else:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    # AI-NOTE: the strip is judged on the weakest channel: digits are white, the sand / skin / green right of the pill end
    # (partly covering the strip, so no 'as tall as the strip' blob) have a weak channel far below the 170 threshold
    strip = np.ascontiguousarray(crop[:, x1 - x0:, :3].min(axis=2)) if crop.ndim == 3 else gray[:, x1 - x0:]
    gray = np.ascontiguousarray(gray[:, :x1 - x0])
    peak = int(gray.max()) if gray.size else 0
    gray, strip = _undim(gray, peak), _undim(strip, peak)    # the strip is stretched like the box
    # AI-NOTE: a number wider than the box is cut at its edge and the visible left part reads as a clean, shorter, wrong
    # value (SP 1234567 -> 123456, price 2500 -> 250); a digit-sized blob right of the box means the box does not hold it all
    if _digits_beyond(strip):
        return None
    r = read_crop(gray, kind)
    return r if r is not None and lo <= r <= hi else None


def read_sp(frame_rgb):
    """SP above 소환 as int in 0..9_999_999, or None."""
    return _read(frame_rgb, SP_BOX, "sp", 0, MAX_SP)


def read_summon_cost(frame_rgb):
    """Summon cost on the 소환 button as int in 1..99_999, or None."""
    return _read(frame_rgb, COST_BOX, "cost", 1, MAX_COST)


def read_panel_sp(frame_rgb):
    """SP shown on the open power panel as int in 0..9_999_999, or None."""
    return _read(frame_rgb, PANEL_SP_BOX, "panelsp", 0, MAX_SP)


def read_price(frame_rgb, button_uv):
    """Price on the buy button centred at button_uv = (u, v), as gear.power_buttons returns it, int in 1..999_999 or None."""
    try:
        u, v = float(button_uv[0]), float(button_uv[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if not (math.isfinite(u) and math.isfinite(v)):
        return None
    du0, dv0, du1, dv1 = PRICE_BOX
    return _read(frame_rgb, (u + du0, v + dv0, u + du1, v + dv1), "price", 1, MAX_PRICE, min_channel=True)
