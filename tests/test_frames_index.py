"""The event -> frame lookup that the whole dataset alignment rests on.

If this is off by one, every action in the dataset is attached to the wrong
frame and nothing downstream will say so. Spec 03 §2.2.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rdom.recorder.frames_index import (
    FrameRec,
    frame_at_or_before,
    load_frames,
    parse_frames,
)


def series(n: int, fps: int = 30, t0: float = 100.0, seg_len: int = 5) -> list[FrameRec]:
    return [
        FrameRec(i=i, seg=i // seg_len, si=i % seg_len, t=t0 + i / fps, dup=False)
        for i in range(n)
    ]


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.frames = series(20)

    def test_exact_hit_returns_that_frame(self):
        for k in (0, 7, 19):
            self.assertEqual(frame_at_or_before(self.frames, self.frames[k].t).i, k)

    def test_between_frames_returns_the_earlier_one(self):
        mid = (self.frames[5].t + self.frames[6].t) / 2
        self.assertEqual(frame_at_or_before(self.frames, mid).i, 5)

    def test_just_before_a_frame_returns_the_previous(self):
        self.assertEqual(
            frame_at_or_before(self.frames, self.frames[6].t - 1e-9).i, 5
        )

    def test_before_first_frame_is_none(self):
        self.assertIsNone(frame_at_or_before(self.frames, self.frames[0].t - 0.001))

    def test_after_last_frame_returns_last(self):
        self.assertEqual(frame_at_or_before(self.frames, 1e9).i, 19)

    def test_empty(self):
        self.assertIsNone(frame_at_or_before([], 1.0))

    def test_segment_seek_key_is_consistent(self):
        f = frame_at_or_before(self.frames, self.frames[12].t)
        self.assertEqual((f.seg, f.si), (2, 2))

    def test_lookup_is_exact_over_a_long_series(self):
        frames = series(10_000)
        for k in (0, 1, 999, 5_000, 9_998, 9_999):
            probe = frames[k].t + 0.5 / 30  # mid-way to the next frame
            self.assertEqual(frame_at_or_before(frames, probe).i, k)


class TestSerialisation(unittest.TestCase):
    def test_roundtrip_through_jsonl(self):
        frames = series(5)
        lines = [json.dumps(f.to_json()) for f in frames]
        back = parse_frames(lines)
        self.assertEqual(len(back), 5)
        for a, b in zip(frames, back):
            self.assertEqual((a.i, a.seg, a.si, a.dup), (b.i, b.seg, b.si, b.dup))
            self.assertAlmostEqual(a.t, b.t, places=6)

    def test_blank_lines_are_skipped(self):
        self.assertEqual(len(parse_frames(['', '  ', json.dumps(series(1)[0].to_json())])), 1)

    def test_load_from_disk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "frames.jsonl"
            p.write_text("\n".join(json.dumps(f.to_json()) for f in series(3)) + "\n")
            self.assertEqual([f.i for f in load_frames(p)], [0, 1, 2])

    def test_dup_defaults_false_when_absent(self):
        self.assertFalse(parse_frames(['{"i":0,"seg":0,"si":0,"t":1.0}'])[0].dup)


if __name__ == "__main__":
    unittest.main()
