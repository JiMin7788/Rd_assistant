"""R3 verification against a real ffmpeg: logged frames == decoded frames.

This is the check the whole alignment design rests on (spec §2.2). If the
encoder ever drops or duplicates a frame relative to ``frames.jsonl``, every
action label in the session shifts and nothing downstream reports it. So the
segment rotation is exercised end to end here rather than trusted.

Needs ffmpeg/ffprobe on PATH; skipped otherwise. No Windows or dxcam involved.
"""

from __future__ import annotations

import json
import queue
import shutil
import tempfile
import unittest
from pathlib import Path

from rdom.recorder.capture import Frame
from rdom.recorder.encoder import SegmentEncoder, build_ffmpeg_cmd, probe_encoder
from rdom.recorder.frames_index import load_frames
from rdom.recorder.session import JsonlWriter
from rdom.recorder.verify import verify_frames, verify_segments

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
W, H = 32, 24


class Buf:
    """Stand-in for the ndarray the capture loop hands over."""

    __slots__ = ("_b",)

    def __init__(self, fill: int) -> None:
        self._b = bytes([fill % 256]) * (W * H * 3)

    def tobytes(self) -> bytes:
        return self._b


class TestBuildCmd(unittest.TestCase):
    def test_scale_filter_only_when_resizing(self):
        same = build_ffmpeg_cmd(W, H, W, H, 30, "libx264", 23, Path("o.mp4"))
        self.assertNotIn("-vf", same)
        smaller = build_ffmpeg_cmd(1600, 900, 1280, 720, 30, "libx264", 23, Path("o.mp4"))
        self.assertIn("scale=1280:720:flags=bicubic", smaller)

    def test_frame_passthrough_is_set(self):
        """Without passthrough ffmpeg may drop or repeat frames to hit the rate,
        which would silently break the 1:1 mapping with frames.jsonl."""
        cmd = build_ffmpeg_cmd(W, H, W, H, 30, "libx264", 23, Path("o.mp4"))
        self.assertEqual(cmd[cmd.index("-fps_mode") + 1], "passthrough")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not available")
    def test_unavailable_codec_falls_back(self):
        self.assertEqual(probe_encoder("definitely_not_a_codec"), "libx264")
        self.assertEqual(probe_encoder("libx264"), "libx264")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not available")
class TestSegmentEncoder(unittest.TestCase):
    def encode(self, n_frames: int, segment_frames: int, fps: int = 30):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        video = root / "video"
        video.mkdir()
        warns: list[tuple[str, dict]] = []

        q: queue.Queue = queue.Queue()
        writer = JsonlWriter(root / "frames.jsonl")
        enc = SegmentEncoder(
            in_q=q, video_dir=video, frames_writer=writer,
            src_res=(W, H), out_res=(W, H), fps=fps,
            codec="libx264", crf=28, segment_frames=segment_frames,
            on_warn=lambda c, d: warns.append((c, d)),
        )
        enc.start()
        for k in range(n_frames):
            q.put(Frame(t=100.0 + k / fps, dup=(k % 17 == 0), data=Buf(k * 9)))
        enc.stop()
        writer.close()
        return root, video, warns

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_decoded_count_matches_log_across_segment_rotation(self):
        root, video, warns = self.encode(n_frames=25, segment_frames=10)

        frames = load_frames(root / "frames.jsonl")
        self.assertEqual(len(frames), 25)
        self.assertEqual([f.i for f in frames], list(range(25)))
        self.assertEqual([f.seg for f in frames], [0] * 10 + [1] * 10 + [2] * 5)
        self.assertEqual([f.si for f in frames[:10]], list(range(10)))
        self.assertEqual([f.si for f in frames[10:20]], list(range(10)))

        self.assertEqual(sorted(p.name for p in video.glob("*.mp4")),
                         ["seg_00000.mp4", "seg_00001.mp4", "seg_00002.mp4"])

        report = verify_segments(video, frames)
        self.assertTrue(report.ok, [c.detail for c in report.failures()])
        self.assertEqual(warns, [])

    def test_single_segment_session(self):
        root, video, _ = self.encode(n_frames=12, segment_frames=1000)
        frames = load_frames(root / "frames.jsonl")
        self.assertEqual({f.seg for f in frames}, {0})
        self.assertTrue(verify_segments(video, frames).ok)

    def test_exact_segment_boundary_does_not_emit_an_empty_segment(self):
        root, video, _ = self.encode(n_frames=20, segment_frames=10)
        frames = load_frames(root / "frames.jsonl")
        self.assertEqual({f.seg for f in frames}, {0, 1})
        self.assertEqual(len(list(video.glob("*.mp4"))), 2)
        self.assertTrue(verify_segments(video, frames).ok)

    def test_full_session_verification_passes(self):
        """The same three reports the recorder runs at shutdown."""
        root, video, _ = self.encode(n_frames=30, segment_frames=10)
        frames = load_frames(root / "frames.jsonl")
        self.assertTrue(verify_frames(frames, max_dup_ratio=0.10).ok)
        self.assertTrue(verify_segments(video, frames).ok)

    def test_dup_flag_survives_the_round_trip(self):
        root, _, _ = self.encode(n_frames=20, segment_frames=10)
        frames = load_frames(root / "frames.jsonl")
        self.assertEqual([f.i for f in frames if f.dup], [0, 17])

    def test_jsonl_is_valid_line_delimited_json(self):
        root, _, _ = self.encode(n_frames=5, segment_frames=10)
        for line in (root / "frames.jsonl").read_text().splitlines():
            if line.strip():
                json.loads(line)


if __name__ == "__main__":
    unittest.main()
