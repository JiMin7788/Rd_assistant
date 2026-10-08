"""R8 verification: the overlay lands markers on the frames the math says.

Built against a synthetic session with known frame times and known action
times, so the frame arithmetic is checked exactly rather than by eye. The
eyeball pass on real footage is still required (spec §9) -- this only proves
the tool is not lying about which frame it drew on.

Also covers the two aspect/derivation fixes from the 2026-09-15 gate run:
``plan_out_res`` and the chrome probe.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rdom.recorder.encoder import plan_out_res
from rdom.recorder.frames_index import FrameRec
from rdom.recorder.probe import profile_edges, suggest_chrome
from rdom.tools.replay_overlay import (
    build_filter_graph,
    frame_index_at,
    load_session,
    plan_markers,
    render,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
FPS = 30
OUT_W, OUT_H = 180, 320  # portrait, like the real capture


class TestPlanOutRes(unittest.TestCase):
    def test_portrait_capture_keeps_its_aspect(self):
        """The bug this replaces: 1499x2108 forced into 720x1280 squeezed the
        picture horizontally by 21% and nothing reported it."""
        w, h = plan_out_res(1499, 2108, 1280)
        self.assertEqual(h, 1280)
        self.assertAlmostEqual(w / h, 1499 / 2108, places=2)
        self.assertNotEqual((w, h), (720, 1280))

    def test_landscape_capture(self):
        self.assertEqual(plan_out_res(1600, 900, 1280), (1280, 720))

    def test_never_upscales(self):
        self.assertEqual(plan_out_res(640, 360, 1280), (640, 360))

    def test_both_edges_even_for_yuv420p(self):
        for src in [(1499, 2108), (1001, 999), (333, 777), (1459, 2068)]:
            w, h = plan_out_res(*src, 1280)
            self.assertEqual((w % 2, h % 2), (0, 0), src)

    def test_square(self):
        self.assertEqual(plan_out_res(1000, 1000, 512), (512, 512))

    def test_rejects_degenerate_source(self):
        with self.assertRaises(ValueError):
            plan_out_res(0, 100, 1280)


class TestChromeProbe(unittest.TestCase):
    @staticmethod
    def frame(w, h, chrome, chrome_rgb=(34, 34, 45), game_rgb=(39, 54, 123)):
        f = [[list(chrome_rgb) for _ in range(w)] for _ in range(h)]
        for y in range(chrome["top"], h - chrome["bottom"]):
            for x in range(chrome["left"], w - chrome["right"]):
                f[y][x] = list(game_rgb)
        return f

    def test_suggests_the_uniform_bands(self):
        chrome = {"left": 3, "top": 8, "right": 6, "bottom": 0}
        got = suggest_chrome(profile_edges(self.frame(60, 90, chrome), step=1))
        self.assertEqual(got["top"], 8)
        self.assertEqual(got["left"], 3)
        self.assertEqual(got["right"], 6)

    def test_no_chrome_suggests_zero(self):
        got = suggest_chrome(
            profile_edges(self.frame(40, 60, {"left": 0, "top": 0, "right": 0, "bottom": 0}), step=1)
        )
        self.assertEqual(got, {"left": 0, "top": 0, "right": 0, "bottom": 0})

    def test_uniform_frame_reports_no_boundary_rather_than_guessing(self):
        """All-chrome and no-chrome look identical; 0 means "not found"."""
        flat = [[[32, 32, 58] for _ in range(50)] for _ in range(50)]
        self.assertEqual(
            suggest_chrome(profile_edges(flat, step=1)),
            {"left": 0, "top": 0, "right": 0, "bottom": 0},
        )

    def test_one_sided_chrome_does_not_leak_into_the_other_edges(self):
        chrome = {"left": 0, "top": 12, "right": 0, "bottom": 0}
        got = suggest_chrome(profile_edges(self.frame(60, 120, chrome), step=1))
        self.assertEqual(got["top"], 12)
        self.assertEqual((got["left"], got["right"], got["bottom"]), (0, 0, 0))

    def test_empty_frame(self):
        self.assertEqual(
            suggest_chrome(profile_edges([])), {"left": 0, "top": 0, "right": 0, "bottom": 0}
        )

    def test_ldplayer_shaped_frame(self):
        """Regression against the real 2026-09-15 capture, reproduced:

        a top bar interrupted by text/icons, a flat right sidebar, a 1px window
        border, and a smooth game gradient running to the bottom edge. Measured
        by hand from that frame: top 40, right 40, left ~1, bottom 0.
        """
        w, h = 300, 420
        top, right = 40, 40
        chrome = (34, 34, 45)
        f = [[list(chrome) for _ in range(w)] for _ in range(h)]

        for y in range(h):
            for x in range(w):
                if y < top or x >= w - right or x == 0:
                    continue
                # Game: a smooth vertical gradient, flat near the bottom edge.
                g = int(40 + 110 * (y - top) / (h - top))
                f[y][x] = [g, 54, 123 + (g // 3)]
        for y in range(14, 27):  # tab-bar glyphs interrupt the top band
            for x in range(20, 120):
                f[y][x] = [48, 47, 59]

        got = suggest_chrome(profile_edges(f, step=2))
        self.assertEqual(got["top"], top, "top bar text must not truncate the band")
        self.assertEqual(got["right"], right)
        self.assertEqual(got["bottom"], 0, "a game gradient must not read as chrome")
        self.assertLessEqual(got["left"], 2)


def make_session(root: Path, n_frames: int, actions: list[tuple[float, float, float]],
                 seg_len: int = 1000, offset_ms: float = 100.0) -> list[FrameRec]:
    """Synthetic session: real mp4, matching frames.jsonl, known action times."""
    (root / "video").mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size={OUT_W}x{OUT_H}:rate={FPS}:duration={n_frames / FPS}",
         "-frames:v", str(n_frames), "-c:v", "libx264", "-crf", "28",
         "-pix_fmt", "yuv420p", str(root / "video" / "seg_00000.mp4")],
        check=True, capture_output=True,
    )
    frames = [
        FrameRec(i=i, seg=i // seg_len, si=i % seg_len, t=1000.0 + i / FPS, dup=(i % 50 == 7))
        for i in range(n_frames)
    ]
    (root / "frames.jsonl").write_text(
        "\n".join(json.dumps(f.to_json()) for f in frames) + "\n", encoding="utf-8"
    )
    events = [
        {"t": t, "ev": "action", "kind": "tap", "t_end": t + 0.08,
         "dur_ms": 80.0, "path_n": 0, "dist_n": 0.0, "at": {"u": u, "v": v}}
        for t, u, v in actions
    ]
    (root / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    (root / "session.json").write_text(json.dumps({
        "session_id": "synthetic",
        "schema_version": 2,
        "clock": "perf_counter",
        "env": {"chrome": {"left": 0, "top": 0, "right": 0, "bottom": 0}},
        "capture": {"target_fps": FPS, "out_res": [OUT_W, OUT_H], "covers": "content"},
        "calib": {"capture_offset_ms": offset_ms},
    }), encoding="utf-8")
    return frames


class TestMarkerMath(unittest.TestCase):
    def setUp(self):
        self.frames = [
            FrameRec(i=i, seg=0, si=i, t=1000.0 + i / FPS, dup=False) for i in range(300)
        ]

    def test_frame_lookup_matches_the_recorder_index(self):
        self.assertEqual(frame_index_at(self.frames, 1000.0), 0)
        self.assertEqual(frame_index_at(self.frames, 1000.0 + 10 / FPS), 10)
        self.assertIsNone(frame_index_at(self.frames, 999.0))

    def test_offset_moves_the_corrected_marker_forward(self):
        t = 1000.0 + 100 / FPS
        markers = plan_markers(
            self.frames, [{"ev": "action", "t": t, "kind": "tap", "at": {"u": 0.5, "v": 0.5}}],
            0, 300, OUT_W, OUT_H, offset_ms=100.0,
        )
        self.assertEqual(len(markers), 2)
        uncorrected, corrected = sorted(markers, key=lambda m: m.local_frame)
        self.assertEqual(uncorrected.local_frame, 100)
        self.assertEqual(corrected.local_frame, 103)  # 100ms at 30fps = 3 frames
        self.assertNotEqual(uncorrected.color, corrected.color)

    def test_uv_maps_onto_video_pixels(self):
        markers = plan_markers(
            self.frames, [{"ev": "action", "t": 1000.0, "kind": "tap",
                           "at": {"u": 0.25, "v": 0.75}}],
            0, 300, OUT_W, OUT_H, offset_ms=0.0,
        )
        self.assertEqual((markers[0].x, markers[0].y), (int(0.25 * OUT_W), int(0.75 * OUT_H)))

    def test_drag_uses_its_start_point(self):
        markers = plan_markers(
            self.frames, [{"ev": "action", "t": 1000.0, "kind": "drag",
                           "from": {"u": 0.1, "v": 0.2}, "to": {"u": 0.9, "v": 0.2}}],
            0, 300, OUT_W, OUT_H, offset_ms=0.0,
        )
        self.assertEqual(markers[0].x, int(0.1 * OUT_W))

    def test_actions_outside_the_window_are_skipped(self):
        far = [{"ev": "action", "t": 1000.0 + 500 / FPS, "kind": "tap",
                "at": {"u": 0.5, "v": 0.5}}]
        self.assertEqual(plan_markers(self.frames, far, 0, 100, OUT_W, OUT_H, 0.0), [])

    def test_non_action_events_ignored(self):
        evs = [{"ev": "mouse_down", "t": 1000.0, "u": 0.5, "v": 0.5},
               {"ev": "warn", "t": 1000.0, "code": "x"}]
        self.assertEqual(plan_markers(self.frames, evs, 0, 300, OUT_W, OUT_H, 0.0), [])


class TestFilterGraph(unittest.TestCase):
    def test_graph_is_never_empty(self):
        """An empty -vf argument makes ffmpeg fail instead of passing frames."""
        g = build_filter_graph([], [], 0, 0, OUT_W, OUT_H, None)
        self.assertEqual(g, "null")

    def test_dup_frames_get_a_flag(self):
        frames = [FrameRec(i=i, seg=0, si=i, t=float(i), dup=(i == 3)) for i in range(10)]
        g = build_filter_graph([], frames, 0, 10, OUT_W, OUT_H, None)
        self.assertIn("orange", g)
        self.assertIn("eq(n\\,3)", g)

    def test_markers_stay_inside_the_frame(self):
        """A click at the far corner must not put the box off-canvas, which
        ffmpeg accepts silently and draws as nothing."""
        import re

        frames = [FrameRec(i=0, seg=0, si=0, t=0.0, dup=False)]
        evs = [
            {"ev": "action", "t": 0.0, "kind": "tap", "at": {"u": u, "v": v}}
            for u, v in [(0.999, 0.999), (0.0, 0.0), (0.5, 0.999), (0.999, 0.0)]
        ]
        markers = plan_markers(frames, evs, 0, 1, OUT_W, OUT_H, 0.0)
        self.assertTrue(markers)
        g = build_filter_graph(markers, frames, 0, 1, OUT_W, OUT_H, None)

        boxes = re.findall(r"drawbox=x=(\d+):y=(\d+):w=(\d+):h=(\d+)", g)
        self.assertEqual(len(boxes), len(markers))
        for x, y, w, h in ((int(a) for a in b) for b in boxes):
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, OUT_W)
            self.assertLessEqual(y + h, OUT_H)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not available")
class TestRenderEndToEnd(unittest.TestCase):
    def test_renders_the_requested_window(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "sess"
            make_session(root, 200, [(1000.0 + k / FPS, 0.3, 0.4) for k in (20, 60, 120)])
            out = Path(d) / "overlay.mp4"
            info = render(root, out, start_frame=10, n_frames=90, offset_ms=100.0)

            self.assertTrue(out.exists() and out.stat().st_size > 0)
            self.assertEqual(info["frames"], 90)
            self.assertEqual(info["frame_range"], [10, 99])
            self.assertEqual(info["actions"], 2)  # frame 120 is past the window
            self.assertEqual(info["out_res"], [OUT_W, OUT_H])

            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                 "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(out)],
                capture_output=True, text=True, check=True,
            )
            st = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(int(st["nb_read_frames"]), 90)
            self.assertEqual((st["width"], st["height"]), (OUT_W, OUT_H))

    def test_window_spanning_two_segments_is_refused_with_a_hint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "sess"
            make_session(root, 120, [(1000.0, 0.5, 0.5)], seg_len=50)
            with self.assertRaises(SystemExit) as cm:
                render(root, Path(d) / "o.mp4", start_frame=40, n_frames=30, offset_ms=0.0)
            self.assertIn("spans segments", str(cm.exception))

    def test_old_schema_is_refused_rather_than_silently_misdrawn(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "sess"
            make_session(root, 60, [(1000.0, 0.5, 0.5)])
            doc = json.loads((root / "session.json").read_text())
            doc["schema_version"] = 1
            (root / "session.json").write_text(json.dumps(doc))
            with self.assertRaises(SystemExit) as cm:
                load_session(root)
            self.assertIn("too old", str(cm.exception))

    def test_capture_covering_the_whole_client_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "sess"
            make_session(root, 60, [(1000.0, 0.5, 0.5)])
            doc = json.loads((root / "session.json").read_text())
            doc["capture"]["covers"] = "client"
            (root / "session.json").write_text(json.dumps(doc))
            with self.assertRaises(SystemExit) as cm:
                load_session(root)
            self.assertIn("covers", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
