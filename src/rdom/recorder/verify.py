"""End-of-session self-verification (spec 03 §8).

A session that fails any check is marked ``CORRUPT`` in ``session.json``.
Silent corruption is the failure mode this whole module exists to prevent: a
one-frame index slip would mislabel every action in the session and would not
be noticed until the model refused to learn.

The jsonl checks are pure and unit-tested. The container decode count needs
ffprobe and is skipped (not failed) when it is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .frames_index import FrameRec

__all__ = ["Check", "VerifyReport", "verify_frames", "verify_events", "verify_segments"]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, skipped: bool = False) -> None:
        self.checks.append(Check(name, ok, detail, skipped))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if not c.skipped)

    @property
    def status(self) -> str:
        return "OK" if self.ok else "CORRUPT"

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "skipped": c.skipped}
                for c in self.checks
            ],
        }

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.skipped]


def verify_frames(
    frames: Sequence[FrameRec], max_dup_ratio: float = 0.02
) -> VerifyReport:
    r = VerifyReport()

    r.add("frames_nonempty", len(frames) > 0, f"{len(frames)} frames")
    if not frames:
        return r

    gaps = [
        (a.i, b.i) for a, b in zip(frames, frames[1:]) if b.i != a.i + 1
    ]
    r.add(
        "index_contiguous",
        not gaps and frames[0].i == 0,
        "ok" if not gaps and frames[0].i == 0 else f"first={frames[0].i} gaps={gaps[:5]}",
    )

    regressions = [
        (a.i, b.i) for a, b in zip(frames, frames[1:]) if b.t < a.t
    ]
    r.add(
        "time_monotonic",
        not regressions,
        "ok" if not regressions else f"{len(regressions)} regressions at {regressions[:5]}",
    )

    # Segment frame indices must restart at 0 and run contiguously per segment.
    seg_bad: list[str] = []
    expect: dict[int, int] = {}
    for f in frames:
        want = expect.get(f.seg, 0)
        if f.si != want:
            seg_bad.append(f"i={f.i} seg={f.seg} si={f.si} want={want}")
        expect[f.seg] = f.si + 1
    r.add(
        "segment_indices",
        not seg_bad,
        "ok" if not seg_bad else f"{len(seg_bad)} bad: {seg_bad[:3]}",
    )

    n_dup = sum(1 for f in frames if f.dup)
    ratio = n_dup / len(frames)
    r.add(
        "dup_ratio",
        ratio < max_dup_ratio,
        f"{ratio:.4f} (limit {max_dup_ratio}) -- {n_dup}/{len(frames)}",
    )
    return r


def verify_events(events: Sequence[dict], max_orphan_ratio: float = 0.01) -> VerifyReport:
    r = VerifyReport()

    n_action = sum(1 for e in events if e.get("ev") == "action")
    r.add("actions_present", n_action > 0, f"{n_action} actions")

    n_down = sum(1 for e in events if e.get("ev") == "mouse_down")
    n_up = sum(1 for e in events if e.get("ev") == "mouse_up")
    orphan = abs(n_down - n_up)
    ratio = orphan / n_down if n_down else 0.0
    r.add(
        "orphan_press_ratio",
        ratio < max_orphan_ratio,
        f"{ratio:.4f} (limit {max_orphan_ratio}) -- down={n_down} up={n_up}",
    )

    # ``action`` events carry the press time (spec §3.2) but are written at
    # release, after the raw mouse_up -- so they are legitimately out of file
    # order and only the live event stream is required to be monotonic.
    ts = [e["t"] for e in events if "t" in e and e.get("ev") != "action"]
    ok = all(b >= a for a, b in zip(ts, ts[1:]))
    r.add("time_monotonic", ok, "ok" if ok else "event times out of order")

    # Excluding actions above would otherwise stop checking them at all, so
    # they are checked among themselves: presses happen in order even though
    # each is written at release.
    ats = [e["t"] for e in events if e.get("ev") == "action" and "t" in e]
    a_ok = all(b >= a for a, b in zip(ats, ats[1:]))
    r.add(
        "action_time_monotonic",
        a_ok,
        "ok" if a_ok else f"{sum(1 for a, b in zip(ats, ats[1:]) if b < a)} out of order",
    )

    fatal = [e for e in events if e.get("ev") == "fatal"]
    r.add(
        "no_fatal",
        not fatal,
        "ok" if not fatal else f"{len(fatal)}: {fatal[0].get('code')}",
    )
    return r


def _ffprobe_frame_count(path: Path) -> int | None:
    exe = shutil.which("ffprobe")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [
                exe, "-v", "error",
                "-select_streams", "v:0",
                "-count_frames",
                "-show_entries", "stream=nb_read_frames",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=600, check=True,
        )
        return int(json.loads(out.stdout)["streams"][0]["nb_read_frames"])
    except Exception:
        return None


def verify_segments(video_dir: Path, frames: Sequence[FrameRec]) -> VerifyReport:
    """Decoded frame count per segment must equal what we logged writing it."""
    r = VerifyReport()
    expected: dict[int, int] = {}
    for f in frames:
        expected[f.seg] = expected.get(f.seg, 0) + 1

    if shutil.which("ffprobe") is None:
        r.add("segment_frame_counts", True, "ffprobe unavailable", skipped=True)
        return r

    mismatches: list[str] = []
    missing: list[str] = []
    for seg, want in sorted(expected.items()):
        path = video_dir / f"seg_{seg:05d}.mp4"
        if not path.exists():
            missing.append(path.name)
            continue
        got = _ffprobe_frame_count(path)
        if got is None:
            mismatches.append(f"{path.name}: unreadable")
        elif got != want:
            mismatches.append(f"{path.name}: decoded {got} != logged {want}")

    r.add("segments_present", not missing, "ok" if not missing else f"missing {missing}")
    r.add(
        "segment_frame_counts",
        not mismatches,
        "ok" if not mismatches else "; ".join(mismatches[:3]),
    )
    return r
