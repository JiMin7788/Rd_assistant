"""In-battle score (top centre of the screen), read with the template digit reader.

Exact or nothing, like perception.digits: read_score returns None whenever the box
is not measured yet, the templates are missing or the reader is unsure. ScoreTracker
additionally confirms a value only after two identical consecutive reads, and never a negative,
above-MAX_SCORE or lower-than-confirmed value.
"""
from __future__ import annotations
import cv2

from rdom.perception import digits

# (u0, v0, u1, v1) in content-normalised coordinates; measured on real frames in a later task.
SCORE_BOX = None
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
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    try:
        r = digits.read_number(gray, "score")
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
