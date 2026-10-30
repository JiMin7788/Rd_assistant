"""In-battle score (top centre of the screen), read with the template digit reader.

Exact or nothing, like perception.digits: read_score returns None whenever the box
is not measured yet, the templates are missing or the reader is unsure. ScoreTracker
additionally confirms a value only after two identical consecutive reads, and never a negative,
above-MAX_SCORE or lower-than-confirmed value.
"""
from __future__ import annotations
import cv2

from rdom.perception import digits

# (u0, v0, u1, v1) in content-normalised coordinates (u relative to round(h*9/16), v to h), digits only.
# Measured on H1 battle frames sup20261029_135038/1075.0.png, sup20261029_145953/912.9.png and
# sup20261029_152652/1016.5.png (1244x2224): the yellow digit fill spans u 0.396-0.599 (4 digits), v 0.088-0.122;
# the box adds room for a 5th digit and the outline and stops above the '처치한 몬스터' label (v ~0.127).
# AI-NOTE: v0 = 0.099, not 0.083: late in an H2 game a second row of effect icons sits over the first digits
# (u 0.40-0.47) and its bottom edge reaches v 0.0975, painting over the digit tops (icon bottom measured on
# sup20261030_061946/1040.9.png 0.094, sup20261030_061946/1071.7.png 0.097, support_runs/sup20261030_061946/end.png and
# support_runs/sup20261030_063914/end.png 0.096; an orange timer icon merges with the yellow fill). The box starts below
# that row, so the reader sees the lower ~70 % of every digit (v 0.099-0.122 is icon-free in all of them) and
# digits_score.npz is built from the same cut (data/digits/score_v2).
SCORE_BOX = (0.36, 0.099, 0.64, 0.126)
GLYPH_KW = dict(merge_x=True, vis=0.7)                  # a cut digit falls apart into pieces; see digits.glyphs
MAX_SCORE = 99999


def read_score(frame_rgb):
    """Score as int, or None when unreadable (also while SCORE_BOX is unset or digits_score.npz is missing)."""
    if SCORE_BOX is None:
        return None
    h = frame_rgb.shape[0]; W = round(h * 9 / 16)       # true 9:16 content width, as gear._content_w
    u0, v0, u1, v1 = SCORE_BOX
    crop = frame_rgb[int(v0 * h):int(v1 * h), int(u0 * W):int(u1 * W)]
    if crop.size == 0:
        return None
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)   # AI-NOTE: a 2-D grey frame must give None, not a cv2 error
    try:
        r = digits.read_number(gray, "score", **GLYPH_KW)
    except OSError:                                      # no digits_score.npz yet
        return None
    return int(r) if r else None


class ScoreTracker:
    """Confirms a score after two identical consecutive reads."""

    def __init__(self):
        self.value = None                                # last confirmed score
        self._last = None

    def update(self, read):
        """Feed one read_score result; returns the confirmed score on the read that confirms it, else None."""
        if read is None:
            return None                                  # AI-NOTE: a failed read neither confirms nor resets the pending value
        if read < 0 or read > MAX_SCORE or (self.value is not None and read < self.value):
            return None                                  # AI-NOTE: implausible (in-battle score only rises, one tracker per battle): ignored like a failed read
        confirmed = read == self._last
        self._last = read
        if confirmed:
            self.value = read
            return read
        return None
