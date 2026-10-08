"""Pure coordinate geometry. No platform dependencies, no third-party imports.

Coordinate chain (spec 03 §1.2, §4.2):

    desktop screen px  ->  client rect  ->  minus chrome  ->  minus letterbox
                                                                   |
                                                                   v
                                                      normalized (u, v) in [0, 1)

``chrome`` is the emulator's own window furniture (LDPlayer 14 puts a tab bar
across the top and an icon column down the right). It is measured once and
pinned in config, because it is not black and so cannot be found by the
letterbox scan -- and a chrome inset that is wrong by 40px shifts and rescales
every coordinate in the session without looking broken.

Only ``(u, v)`` is ever persisted. The cell grid is NOT known yet and is
deliberately not modelled here -- ``(u, v) -> cell_index`` belongs to the
dataset builder so that a grid redefinition cannot invalidate recorded data.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

__all__ = ["Rect", "Insets", "Viewport", "detect_letterbox", "fit_chrome", "GAME_ASPECT"]


@dataclass(frozen=True)
class Rect:
    """Half-open pixel rectangle: x in [left, right), y in [top, bottom)."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def translated(self, dx: int, dy: int) -> "Rect":
        return Rect(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)


@dataclass(frozen=True)
class Insets:
    """Per-edge inset in pixels."""

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }


# Game surface aspect (width / height), from the android resolution 1440x2560.
GAME_ASPECT = 1440 / 2560


def fit_chrome(client: Rect, chrome: Insets, aspect: float = GAME_ASPECT) -> Insets:
    """Re-derive the right inset so the content keeps the game's aspect.

    LDPlayer's right icon sidebar can be shown or hidden, so a pinned
    ``chrome.right`` is wrong half the time: with the sidebar hidden, a pinned 39
    cut 39px of game off the right edge and stretched every normalized u
    (2026-10-07 recording). The game always renders 9:16 at full content height,
    so the width follows from the height; whatever is left on the right is chrome.
    """
    h = client.height - chrome.top - chrome.bottom
    w = round(h * aspect)
    right = max(0, client.width - chrome.left - w)
    return Insets(left=chrome.left, top=chrome.top, right=right, bottom=chrome.bottom)


@dataclass(frozen=True)
class Viewport:
    """Maps desktop screen pixels to/from normalized game-content coordinates.

    ``client`` is the emulator window's client area in absolute screen pixels.
    ``chrome`` strips the emulator's own window furniture (measured, config-pinned).
    ``letterbox`` strips black bars inside the game surface (auto-detected).
    """

    client: Rect
    chrome: Insets = Insets()
    letterbox: Insets = Insets()

    def __post_init__(self) -> None:
        c = self.content
        if c.width <= 0 or c.height <= 0:
            raise ValueError(
                f"empty content area: client={self.client.as_tuple()} "
                f"chrome={self.chrome} letterbox={self.letterbox}"
            )

    @property
    def content(self) -> Rect:
        """The game content area in absolute screen pixels."""
        return Rect(
            left=self.client.left + self.chrome.left + self.letterbox.left,
            top=self.client.top + self.chrome.top + self.letterbox.top,
            right=self.client.right - self.chrome.right - self.letterbox.right,
            bottom=self.client.bottom - self.chrome.bottom - self.letterbox.bottom,
        )

    @property
    def inner(self) -> Rect:
        """Client minus chrome, before letterbox. What the capture region covers."""
        return Rect(
            left=self.client.left + self.chrome.left,
            top=self.client.top + self.chrome.top,
            right=self.client.right - self.chrome.right,
            bottom=self.client.bottom - self.chrome.bottom,
        )

    def to_uv(self, sx: int, sy: int) -> tuple[float, float]:
        """Screen px -> normalized. May fall outside [0, 1); caller checks."""
        c = self.content
        return ((sx - c.left) / c.width, (sy - c.top) / c.height)

    def contains(self, sx: int, sy: int) -> bool:
        return self.content.contains(sx, sy)

    def to_screen(self, u: float, v: float) -> tuple[int, int]:
        """Normalized -> screen px. Inverse of :meth:`to_uv`.

        Used by the calibration flash test (spec §6.2) to click a known button.
        """
        c = self.content
        return (int(c.left + u * c.width), int(c.top + v * c.height))


def _profiles(frame) -> tuple[list[int], list[int]]:
    """Per-row and per-column maximum channel value.

    Uses numpy vectorisation when the frame provides it -- a pure-Python scan of
    a 1600x900 frame takes seconds, and this runs on the startup path.
    """
    try:  # numpy ndarray
        m = frame.max(axis=2)
        return m.max(axis=1).tolist(), m.max(axis=0).tolist()
    except (AttributeError, TypeError, ValueError):
        pass
    rows = [max((max(px) for px in row), default=0) for row in frame]
    width = len(frame[0]) if len(frame) else 0
    cols = [max((max(row[x]) for row in frame), default=0) for x in range(width)]
    return rows, cols


def detect_letterbox(frame, threshold: int = 12) -> Insets:
    """Find black bars around ``frame`` (H x W x 3, ndarray or nested lists).

    A frame that is black everywhere would otherwise report the whole image as
    letterbox, so scanning bails out and returns zeros instead of guessing.
    """
    h = len(frame)
    w = len(frame[0]) if h else 0
    if h == 0 or w == 0:
        return Insets()

    rows, cols = _profiles(frame)

    top = 0
    while top < h and rows[top] <= threshold:
        top += 1
    if top == h:  # fully black frame -- refuse to guess
        return Insets()
    bottom = 0
    while bottom < h - top and rows[h - 1 - bottom] <= threshold:
        bottom += 1

    left = 0
    while left < w and cols[left] <= threshold:
        left += 1
    if left == w:
        return Insets()
    right = 0
    while right < w - left and cols[w - 1 - right] <= threshold:
        right += 1

    return Insets(left=left, top=top, right=right, bottom=bottom)


def dist_n(u0: float, v0: float, u1: float, v1: float) -> float:
    """Normalized euclidean distance. Shared by event classification."""
    return hypot(u1 - u0, v1 - v0)
