"""Edge colour profiles used to measure emulator chrome. Pure, stdlib only.

The emulator's tab bar and sidebar are near-uniform dark colours that are NOT
black, so :func:`geometry.detect_letterbox` cannot find them. They are measured
once by eye from these profiles and pinned in config -- chrome that is wrong by
40px shifts and rescales every coordinate in the session without looking broken.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["EdgeProfile", "profile_edges", "suggest_chrome", "band_length"]


@dataclass(frozen=True)
class EdgeProfile:
    """Mean colour of each row (top to bottom) and column (left to right)."""

    rows: list[tuple[int, int, int]]
    cols: list[tuple[int, int, int]]


def _mean(pixels) -> tuple[int, int, int]:
    n = 0
    r = g = b = 0
    for px in pixels:
        r += px[0]
        g += px[1]
        b += px[2]
        n += 1
    return (r // n, g // n, b // n) if n else (0, 0, 0)


def profile_edges(frame, step: int = 4) -> EdgeProfile:
    """Row and column mean colours. ``frame`` is H x W x 3 (ndarray or lists)."""
    h = len(frame)
    w = len(frame[0]) if h else 0
    if not h or not w:
        return EdgeProfile([], [])

    try:  # numpy fast path -- this runs on the startup path
        m = frame[::1, ::step].mean(axis=1).astype(int)
        n = frame[::step, ::1].mean(axis=0).astype(int)
        return EdgeProfile(
            [tuple(int(c) for c in row) for row in m],  # type: ignore[misc]
            [tuple(int(c) for c in col) for col in n],  # type: ignore[misc]
        )
    except (AttributeError, TypeError, IndexError):
        pass

    rows = [_mean(frame[y][x] for x in range(0, w, step)) for y in range(h)]
    cols = [_mean(frame[y][x] for y in range(0, h, step)) for x in range(w)]
    return EdgeProfile(rows, cols)


def _reference(series, k: int = 3) -> tuple[int, int, int]:
    """Per-channel median of the first ``k`` entries.

    The median rather than the first entry, because the outermost row or column
    is often a 1px window border whose colour matches neither chrome nor game.
    """
    sample = list(series[:k]) or [(0, 0, 0)]
    return tuple(sorted(v[c] for v in sample)[len(sample) // 2] for c in range(3))  # type: ignore[return-value]


def band_length(series, tolerance: int, limit: int, k: int = 3) -> int:
    """Width of the edge band whose colour matches the edge's own.

    The *last* matching index is used, not the length of the leading run: the
    emulator's top bar carries text and icons, so it is interrupted, and a run
    test stops at the first glyph and under-reads the inset badly.

    Returns 0 when the band reaches ``limit``, and also when the band does not
    end in a hard step. A smooth gradient in the game's own artwork drifts out
    of tolerance eventually and would otherwise be reported as a confident
    inset; reporting 0 sends the human to the printed profile instead, which is
    the safe direction to be wrong in.
    """
    if not len(series):
        return 0
    ref = _reference(series, k)
    limit = min(limit, len(series))

    last = -1
    for i in range(limit):
        if max(abs(a - b) for a, b in zip(series[i], ref)) <= tolerance:
            last = i
    if last < 0 or last >= limit - 1:
        return 0

    step = max(abs(a - b) for a, b in zip(series[last + 1], ref))
    return last + 1 if step >= max(2 * tolerance, 16) else 0


def suggest_chrome(
    prof: EdgeProfile, tolerance: int = 8, max_fraction: float = 0.15
) -> dict[str, int]:
    """First guess at chrome insets, from the colour band at each edge.

    A *suggestion* only -- always eyeball the printed profile before writing
    these into config. It reliably finds a flat sidebar and an interrupted top
    bar, but reports 0 ("no boundary found") wherever the game's own artwork
    happens to match the edge colour. Chrome that is wrong by 40px shifts and
    rescales every coordinate in the session without ever looking broken.
    """
    out = {"left": 0, "top": 0, "right": 0, "bottom": 0}
    if not prof.rows or not prof.cols:
        return out

    row_cap = max(2, int(len(prof.rows) * max_fraction))
    col_cap = max(2, int(len(prof.cols) * max_fraction))

    out["top"] = band_length(prof.rows, tolerance, row_cap)
    out["bottom"] = band_length(prof.rows[::-1], tolerance, row_cap)
    out["left"] = band_length(prof.cols, tolerance, col_cap)
    out["right"] = band_length(prof.cols[::-1], tolerance, col_cap)
    return out
