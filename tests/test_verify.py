"""Spec §8 self-verification, plus the session fingerprint and jsonl writer.

Each check is exercised on a deliberately broken session, because a check that
has never failed in a test is a check that might not be able to fail at all.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from rdom.recorder.frames_index import FrameRec
from rdom.recorder.session import JsonlWriter, Session, env_fingerprint
from rdom.recorder.verify import verify_events, verify_frames, verify_segments


def frames(n: int, seg_len: int = 5) -> list[FrameRec]:
    return [
        FrameRec(i=i, seg=i // seg_len, si=i % seg_len, t=100.0 + i / 30, dup=False)
        for i in range(n)
    ]


def named(report):
    return {c.name: c for c in report.checks}


class TestVerifyFrames(unittest.TestCase):
    def test_clean_session_passes(self):
        r = verify_frames(frames(30))
        self.assertTrue(r.ok, r.failures())
        self.assertEqual(r.status, "OK")

    def test_empty_session_fails(self):
        self.assertFalse(verify_frames([]).ok)

    def test_index_gap_is_caught(self):
        f = frames(10)
        del f[4]
        c = named(verify_frames(f))
        self.assertFalse(c["index_contiguous"].ok)

    def test_index_not_starting_at_zero_is_caught(self):
        f = [replace(x, i=x.i + 1) for x in frames(5)]
        self.assertFalse(named(verify_frames(f))["index_contiguous"].ok)

    def test_time_regression_is_caught(self):
        f = frames(10)
        f[6] = replace(f[6], t=f[2].t)
        self.assertFalse(named(verify_frames(f))["time_monotonic"].ok)

    def test_segment_index_restart_is_enforced(self):
        f = frames(10, seg_len=5)
        f[5] = replace(f[5], si=3)  # should be 0 at a segment boundary
        self.assertFalse(named(verify_frames(f))["segment_indices"].ok)

    def test_dup_ratio_limit(self):
        f = frames(100)
        for k in range(3):
            f[k] = replace(f[k], dup=True)
        self.assertTrue(named(verify_frames(f, 0.02))["dup_ratio"].ok is False)
        self.assertTrue(named(verify_frames(f, 0.05))["dup_ratio"].ok)

    def test_report_status_flips_to_corrupt(self):
        f = frames(10)
        f[3] = replace(f[3], t=0.0)
        self.assertEqual(verify_frames(f).status, "CORRUPT")


class TestVerifyEvents(unittest.TestCase):
    @staticmethod
    def stream(n_gestures: int = 3, drop_last_up: bool = False) -> list[dict]:
        out: list[dict] = []
        t = 0.0
        for _ in range(n_gestures):
            out.append({"t": t, "ev": "mouse_down"})
            out.append({"t": t + 0.05, "ev": "mouse_up"})
            out.append({"t": t, "ev": "action", "kind": "tap"})
            t += 1.0
        if drop_last_up:
            out = [e for e in out if e is not out[-2]]
        return sorted(out, key=lambda e: e["t"])

    def test_clean_stream_passes(self):
        self.assertTrue(verify_events(self.stream(200)).ok)

    def test_no_actions_means_the_hook_never_attached(self):
        c = named(verify_events([{"t": 0.0, "ev": "warn", "code": "x"}]))
        self.assertFalse(c["actions_present"].ok)

    def test_orphan_presses_over_threshold(self):
        ev = self.stream(10)
        ev.append({"t": 99.0, "ev": "mouse_down"})  # 1 of 11 unmatched
        self.assertFalse(named(verify_events(ev))["orphan_press_ratio"].ok)

    def test_a_single_orphan_in_a_large_stream_is_tolerated(self):
        ev = self.stream(500)
        ev.append({"t": 9999.0, "ev": "mouse_down"})
        self.assertTrue(named(verify_events(ev))["orphan_press_ratio"].ok)

    def test_fatal_event_fails_the_session(self):
        ev = self.stream(5)
        ev.append({"t": 9.0, "ev": "fatal", "code": "window_changed"})
        c = named(verify_events(ev))
        self.assertFalse(c["no_fatal"].ok)
        self.assertIn("window_changed", c["no_fatal"].detail)

    def test_out_of_order_raw_timestamps_caught(self):
        ev = [{"t": 5.0, "ev": "mouse_down"}, {"t": 1.0, "ev": "mouse_up"}]
        self.assertFalse(named(verify_events(ev))["time_monotonic"].ok)

    def test_action_written_after_its_mouse_up_is_not_a_violation(self):
        """An action carries the PRESS time but is written at release, so it is
        legitimately earlier than the mouse_up line just above it."""
        ev = [
            {"t": 1.0, "ev": "mouse_down"},
            {"t": 1.09, "ev": "mouse_up"},
            {"t": 1.0, "ev": "action", "kind": "tap"},
        ]
        c = named(verify_events(ev))
        self.assertTrue(c["time_monotonic"].ok)
        self.assertTrue(c["action_time_monotonic"].ok)

    def test_reordered_actions_are_still_caught(self):
        ev = [
            {"t": 5.0, "ev": "action", "kind": "tap"},
            {"t": 1.0, "ev": "action", "kind": "tap"},
        ]
        self.assertFalse(named(verify_events(ev))["action_time_monotonic"].ok)


class TestVerifySegments(unittest.TestCase):
    def test_missing_segment_file_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            r = verify_segments(Path(d), frames(10, seg_len=5))
            self.assertFalse(named(r)["segments_present"].ok)

    def test_present_files_pass_presence_check(self):
        with tempfile.TemporaryDirectory() as d:
            for s in (0, 1):
                (Path(d) / f"seg_{s:05d}.mp4").write_bytes(b"")
            self.assertTrue(named(verify_segments(Path(d), frames(10, 5)))["segments_present"].ok)


class TestFingerprint(unittest.TestCase):
    ENV = {
        "emulator": {"name": "LDPlayer", "version": "9.1.34", "instance": "LDPlayer-0"},
        "android_res": [1600, 900],
        "android_dpi": 240,
        "game_version": "1.4.2",
        "game_gfx_preset": "high",
        "chrome": {"left": 1, "top": 40, "right": 40, "bottom": 0},
        "letterbox": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "win_dpi_scale": 1.0,
        "window_client_rect_screen": [104, 132, 1704, 1032],
    }
    CAP = {"out_res": [910, 1280], "target_fps": 30, "covers": "content"}

    def fp(self, **over):
        env = json.loads(json.dumps(self.ENV))
        env.update(over)
        return env_fingerprint(env, self.CAP)

    def test_stable_across_runs(self):
        self.assertEqual(self.fp(), self.fp())

    def test_window_position_does_not_change_it(self):
        """Coordinates are normalized, so a moved window is still compatible."""
        self.assertEqual(self.fp(window_client_rect_screen=[0, 0, 1600, 900]), self.fp())

    def test_resolution_change_breaks_compatibility(self):
        self.assertNotEqual(self.fp(android_res=[1280, 720]), self.fp())

    def test_dpi_change_breaks_compatibility(self):
        self.assertNotEqual(self.fp(android_dpi=320), self.fp())

    def test_game_version_change_breaks_compatibility(self):
        self.assertNotEqual(self.fp(game_version="1.5.0"), self.fp())

    def test_letterbox_change_breaks_compatibility(self):
        self.assertNotEqual(
            self.fp(letterbox={"left": 8, "top": 0, "right": 8, "bottom": 0}), self.fp()
        )

    def test_output_resolution_change_breaks_compatibility(self):
        self.assertNotEqual(
            env_fingerprint(self.ENV, {"out_res": [720, 1280], "target_fps": 30,
                                       "covers": "content"}), self.fp()
        )

    def test_chrome_change_breaks_compatibility(self):
        """Chrome defines where the content area starts -- it must be pinned."""
        self.assertNotEqual(
            self.fp(chrome={"left": 0, "top": 0, "right": 40, "bottom": 0}), self.fp()
        )

    def test_covers_change_breaks_compatibility(self):
        self.assertNotEqual(
            env_fingerprint(self.ENV, {"out_res": [910, 1280], "target_fps": 30,
                                       "covers": "client"}), self.fp()
        )


class TestJsonlWriterAndSession(unittest.TestCase):
    def test_writer_preserves_order_and_flushes_on_close(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.jsonl"
            w = JsonlWriter(p, flush_every=7)
            for i in range(500):
                w.write({"i": i})
            w.close()
            rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
            self.assertEqual([r["i"] for r in rows], list(range(500)))
            self.assertEqual(w.n_written, 500)

    def test_session_layout_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session.create(Path(d))
            self.assertTrue(s.video_dir.is_dir())
            self.assertTrue((s.root / "calib").is_dir())
            s.frames.write({"i": 0})
            s.events.write({"t": 0.0, "ev": "action"})
            s.close()
            path = s.write_manifest(
                TestFingerprint.ENV, TestFingerprint.CAP, None, {"status": "OK"}
            )
            doc = json.loads(path.read_text())
            self.assertEqual(doc["clock"], "perf_counter")
            self.assertTrue(doc["env_fingerprint"].startswith("sha256:"))
            self.assertEqual(doc["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
