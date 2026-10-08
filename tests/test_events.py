"""R5 verification: tap/drag classification and gesture bookkeeping.

The spec's acceptance criterion is 50 deliberate taps + 50 deliberate drags
classified with 100% accuracy; ``test_r5_acceptance_100_taps_and_drags``
reproduces that offline over the same decision function the hook feeds.
"""

from __future__ import annotations

import unittest

from rdom.recorder.events import DOWN, MOVE, UP, Action, Pointer, PointerTracker, classify
from rdom.recorder.geometry import Insets, Rect, Viewport

TAP_R = 0.012
# 1600x900 content: 0.012 normalized ~ 19px horizontally.
VP = Viewport(client=Rect(0, 0, 1640, 900), chrome=Insets(right=40), letterbox=Insets())


class Collector:
    def __init__(self):
        self.raw: list[Pointer] = []
        self.actions: list[Action] = []

    def tracker(self, **kw) -> PointerTracker:
        opts = dict(
            viewport=VP,
            tap_radius_n=TAP_R,
            move_throttle_ms=0.0,
            on_raw=self.raw.append,
            on_action=self.actions.append,
        )
        opts.update(kw)
        return PointerTracker(**opts)


def gesture(tr: PointerTracker, t0: float, start, end, moves=(), dur=0.09):
    tr.feed(t0, DOWN, *start)
    for k, pt in enumerate(moves, 1):
        tr.feed(t0 + dur * k / (len(moves) + 1), MOVE, *pt)
    tr.feed(t0 + dur, UP, *end)


class TestClassify(unittest.TestCase):
    def test_action_time_is_press_not_release(self):
        c = Collector()
        tr = c.tracker()
        gesture(tr, 10.0, (300, 300), (302, 301), dur=0.25)
        a = c.actions[0]
        self.assertEqual(a.t, 10.0)
        self.assertAlmostEqual(a.t_end, 10.25)
        self.assertAlmostEqual(a.dur_ms, 250.0, places=3)

    def test_long_press_without_movement_is_still_a_tap(self):
        """Duration must not influence the tap/drag split (spec §4.2)."""
        c = Collector()
        gesture(c.tracker(), 0.0, (500, 500), (500, 500), dur=3.0)
        self.assertEqual(c.actions[0].kind, "tap")

    def test_fast_long_movement_is_a_drag(self):
        c = Collector()
        gesture(c.tracker(), 0.0, (200, 400), (900, 400), dur=0.05)
        self.assertEqual(c.actions[0].kind, "drag")

    def test_boundary_is_exclusive_below_radius(self):
        down = Pointer(0.0, DOWN, 0, 0, 0.0, 0.0)
        just_under = Pointer(0.1, UP, 0, 0, TAP_R - 1e-9, 0.0)
        just_over = Pointer(0.1, UP, 0, 0, TAP_R + 1e-9, 0.0)
        self.assertEqual(classify(down, [], just_under, TAP_R).kind, "tap")
        self.assertEqual(classify(down, [], just_over, TAP_R).kind, "drag")

    def test_path_count_recorded(self):
        c = Collector()
        tr = c.tracker()
        gesture(tr, 0.0, (200, 400), (900, 400),
                moves=[(300, 400), (500, 400), (700, 400)])
        self.assertEqual(c.actions[0].path_n, 3)


class TestJsonShape(unittest.TestCase):
    def test_tap_json_has_at_only(self):
        c = Collector()
        gesture(c.tracker(), 1.0, (400, 400), (401, 400))
        j = c.actions[0].to_json()
        self.assertEqual(j["ev"], "action")
        self.assertEqual(j["kind"], "tap")
        self.assertIn("at", j)
        self.assertNotIn("from", j)

    def test_drag_json_has_from_and_to(self):
        c = Collector()
        gesture(c.tracker(), 1.0, (200, 400), (900, 400))
        j = c.actions[0].to_json()
        self.assertEqual(j["kind"], "drag")
        self.assertIn("from", j)
        self.assertIn("to", j)
        self.assertNotIn("at", j)

    def test_raw_events_are_emitted_for_audit(self):
        c = Collector()
        tr = c.tracker()
        gesture(tr, 0.0, (200, 400), (900, 400), moves=[(500, 400)])
        self.assertEqual(
            [p.to_json()["ev"] for p in c.raw],
            ["mouse_down", "mouse_move", "mouse_up"],
        )


class TestFiltering(unittest.TestCase):
    def test_clicks_outside_content_are_dropped(self):
        c = Collector()
        tr = c.tracker()
        gesture(tr, 0.0, (1620, 400), (1620, 400))  # inside the 40px sidebar
        self.assertEqual(c.actions, [])
        self.assertEqual(c.raw, [])
        self.assertEqual(tr.n_outside, 2)

    def test_release_outside_still_closes_the_gesture(self):
        """Otherwise the tracker would stay stuck on that press forever."""
        c = Collector()
        tr = c.tracker()
        tr.feed(0.0, DOWN, 400, 400)
        tr.feed(0.1, UP, 1630, 400)
        self.assertEqual(len(c.actions), 1)
        self.assertEqual(c.actions[0].kind, "drag")
        tr.feed(0.2, DOWN, 500, 500)
        tr.feed(0.3, UP, 500, 500)
        self.assertEqual(len(c.actions), 2)
        self.assertEqual(tr.n_orphan_down, 0)

    def test_paused_tracker_records_nothing(self):
        c = Collector()
        tr = c.tracker()
        tr.paused = True
        gesture(tr, 0.0, (400, 400), (400, 400))
        self.assertEqual((c.raw, c.actions), ([], []))

    def test_moves_are_ignored_when_no_button_is_down(self):
        c = Collector()
        tr = c.tracker()
        for i in range(50):
            tr.feed(i * 0.01, MOVE, 400 + i, 400)
        self.assertEqual(c.raw, [])

    def test_move_throttle(self):
        c = Collector()
        tr = c.tracker(move_throttle_ms=20.0)
        tr.feed(0.0, DOWN, 200, 400)
        for i in range(1, 11):  # 10 moves at 5ms spacing
            tr.feed(i * 0.005, MOVE, 200 + i * 10, 400)
        tr.feed(0.06, UP, 400, 400)
        self.assertEqual(c.actions[0].path_n, 2)  # at 20ms and 40ms

    def test_orphan_up_counted_not_crashed(self):
        c = Collector()
        tr = c.tracker()
        tr.feed(0.0, UP, 400, 400)
        self.assertEqual((tr.n_orphan_up, c.actions), (1, []))

    def test_orphan_down_counted_on_relaunch_and_on_close(self):
        c = Collector()
        tr = c.tracker()
        tr.feed(0.0, DOWN, 400, 400)
        tr.feed(0.5, DOWN, 500, 500)  # first press never released
        self.assertEqual(tr.n_orphan_down, 1)
        tr.close()
        self.assertEqual(tr.n_orphan_down, 2)
        self.assertEqual(c.actions, [])


class TestR5Acceptance(unittest.TestCase):
    def test_r5_acceptance_100_taps_and_drags(self):
        """50 taps + 50 drags, 100% classification accuracy (spec §10 R5)."""
        c = Collector()
        tr = c.tracker()
        t = 0.0
        expected: list[str] = []

        for i in range(50):  # jitter within a few px, varied durations
            x, y = 200 + (i % 10) * 120, 150 + (i // 10) * 130
            gesture(tr, t, (x, y), (x + (i % 5) - 2, y + (i % 3) - 1),
                    dur=0.05 + 0.04 * (i % 7))
            expected.append("tap")
            t += 1.0

        for i in range(50):  # displacement well past the 19px threshold
            x, y = 200 + (i % 5) * 140, 150 + (i // 5) * 60  # end stays in bounds
            gesture(tr, t, (x, y), (x + 140, y + 30),
                    moves=[(x + 40, y + 10), (x + 90, y + 20)],
                    dur=0.06 + 0.02 * (i % 4))
            expected.append("drag")
            t += 1.0

        self.assertEqual(len(c.actions), 100)
        self.assertEqual([a.kind for a in c.actions], expected)
        self.assertEqual((tr.n_orphan_down, tr.n_orphan_up, tr.n_outside), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
