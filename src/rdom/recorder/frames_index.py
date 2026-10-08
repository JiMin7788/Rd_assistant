"""Frame index: the bridge between ``events.jsonl`` and the encoded video.

Spec 03 §2.2. MP4 presentation timestamps are never trusted -- every frame
handed to the encoder is logged here at the moment it is written, so an event
at time ``t`` is resolved by binary search over this list instead.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

__all__ = ["FrameRec", "load_frames", "parse_frames", "frame_at_or_before"]


@dataclass(frozen=True)
class FrameRec:
    i: int  # session-global frame index, contiguous from 0
    seg: int  # segment number
    si: int  # frame index within the segment (seek key for the MP4)
    t: float  # perf_counter() stamped immediately after grab()
    dup: bool  # capture produced no new frame; previous one was repeated

    @classmethod
    def from_json(cls, o: dict) -> "FrameRec":
        return cls(
            i=int(o["i"]),
            seg=int(o["seg"]),
            si=int(o["si"]),
            t=float(o["t"]),
            dup=bool(o.get("dup", False)),
        )

    def to_json(self) -> dict:
        return {
            "i": self.i,
            "seg": self.seg,
            "si": self.si,
            "t": round(self.t, 6),
            "dup": self.dup,
        }


def parse_frames(lines: Iterable[str]) -> list[FrameRec]:
    out: list[FrameRec] = []
    for line in lines:
        line = line.strip()
        if line:
            out.append(FrameRec.from_json(json.loads(line)))
    return out


def load_frames(path: str | Path) -> list[FrameRec]:
    with open(path, "r", encoding="utf-8") as fh:
        return parse_frames(fh)


def frame_at_or_before(frames: Sequence[FrameRec], t: float) -> FrameRec | None:
    """Last frame whose capture time is <= ``t``.

    ``frames`` must be sorted by ``t`` (the end-of-session check enforces it).
    Returns ``None`` when ``t`` precedes the first frame.
    """
    idx = bisect_right(_TimeView(frames), t) - 1
    return frames[idx] if idx >= 0 else None


class _TimeView(Sequence[float]):
    """Read-only ``t`` projection so bisect needs no parallel list."""

    __slots__ = ("_frames",)

    def __init__(self, frames: Sequence[FrameRec]) -> None:
        self._frames = frames

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, i):  # type: ignore[override]
        return self._frames[i].t
