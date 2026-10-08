"""R1 verification: coordinate transforms survive window moves and letterboxing."""

from __future__ import annotations

import unittest

from rdom.recorder.geometry import Insets, Rect, Viewport, detect_letterbox, dist_n


def make(client: Rect, sidebar: int = 40, lb: Insets = Insets()) -> Viewport:
    return Viewport(client=client, chrome=Insets(right=sidebar), letterbox=lb)


class TestRect(unittest.TestCase):
    def test_dimensions_and_containment_are_half_open(self):
        r = Rect(10, 20, 110, 70)
        self.assertEqual((r.width, r.height), (100, 50))
        self.assertTrue(r.contains(10, 20))
        self.assertFalse(r.contains(110, 20))  # right edge excluded
        self.assertFalse(r.contains(10, 70))  # bottom edge excluded

    def test_translate(self):
        self.assertEqual(Rect(0, 0, 10, 10).translated(-5, 7).as_tuple(), (-5, 7, 5, 17))


class TestViewport(unittest.TestCase):
    def test_content_excludes_sidebar_and_letterbox(self):
        vp = make(Rect(100, 200, 1700, 1100), sidebar=40, lb=Insets(left=8, right=8))
        self.assertEqual(vp.content.as_tuple(), (108, 200, 1652, 1100))

    def test_chrome_applies_to_every_edge(self):
        """LDPlayer 14 draws a tab bar on top as well as the right sidebar."""
        vp = Viewport(
            client=Rect(0, 0, 1499, 2108),
            chrome=Insets(left=1, top=40, right=40, bottom=0),
        )
        self.assertEqual(vp.content.as_tuple(), (1, 40, 1459, 2108))
        self.assertEqual((vp.content.width, vp.content.height), (1458, 2068))

    def test_inner_is_chrome_removed_before_letterbox(self):
        vp = Viewport(
            client=Rect(0, 0, 100, 200),
            chrome=Insets(left=1, top=40, right=40),
            letterbox=Insets(left=5, right=5),
        )
        self.assertEqual(vp.inner.as_tuple(), (1, 40, 60, 200))
        self.assertEqual(vp.content.as_tuple(), (6, 40, 55, 200))

    def test_chrome_shifts_uv_origin(self):
        """A missing top inset silently rescales and offsets every coordinate."""
        client = Rect(0, 0, 1499, 2108)
        with_chrome = Viewport(client=client, chrome=Insets(left=1, top=40, right=40))
        without = Viewport(client=client, chrome=Insets(right=40))
        self.assertNotEqual(with_chrome.to_uv(700, 1000), without.to_uv(700, 1000))

    def test_corners_map_to_unit_square(self):
        vp = make(Rect(0, 0, 1640, 900))
        c = vp.content
        self.assertEqual(vp.to_uv(c.left, c.top), (0.0, 0.0))
        u, v = vp.to_uv(c.right - 1, c.bottom - 1)
        self.assertLess(u, 1.0)
        self.assertLess(v, 1.0)
        self.assertGreater(u, 0.99)

    def test_click_is_reproducible_across_window_moves(self):
        """R1 acceptance: same content-relative point -> same (u,v) after a move.

        This is the invariant that lets the watchdog treat a window move as
        fatal rather than something to silently correct for.
        """
        base = Rect(0, 0, 1640, 900)
        vp0 = make(base)
        target = vp0.to_uv(400, 300)

        for dx, dy in [(37, 0), (-11, 480), (900, -120), (5, 5), (0, -7),
                       (1234, 56), (-300, 0), (61, 61), (0, 999), (7, -7)]:
            vp = make(base.translated(dx, dy))
            got = vp.to_uv(400 + dx, 300 + dy)
            self.assertAlmostEqual(got[0], target[0], delta=0.002)
            self.assertAlmostEqual(got[1], target[1], delta=0.002)

    def test_to_screen_roundtrips(self):
        vp = make(Rect(103, 217, 1743, 1117))
        for sx, sy in [(200, 300), (1000, 900), (103, 217), (1500, 1100)]:
            u, v = vp.to_uv(sx, sy)
            self.assertEqual(vp.to_screen(u, v), (sx, sy))

    def test_contains_rejects_sidebar_clicks(self):
        vp = make(Rect(0, 0, 1640, 900), sidebar=40)
        self.assertTrue(vp.contains(1599, 450))
        self.assertFalse(vp.contains(1600, 450))  # first sidebar pixel

    def test_degenerate_content_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            make(Rect(0, 0, 40, 900), sidebar=40)
        with self.assertRaises(ValueError):
            make(Rect(0, 0, 200, 100), sidebar=0, lb=Insets(top=50, bottom=50))


class TestLetterbox(unittest.TestCase):
    @staticmethod
    def frame(w, h, box):
        f = [[[0, 0, 0] for _ in range(w)] for _ in range(h)]
        l, t, r, b = box
        for y in range(t, h - b):
            for x in range(l, w - r):
                f[y][x] = [180, 190, 200]
        return f

    def test_finds_symmetric_pillarbox(self):
        self.assertEqual(
            detect_letterbox(self.frame(40, 20, (6, 0, 6, 0))),
            Insets(left=6, top=0, right=6, bottom=0),
        )

    def test_finds_asymmetric_bars(self):
        self.assertEqual(
            detect_letterbox(self.frame(40, 20, (3, 5, 7, 2))),
            Insets(left=3, top=5, right=7, bottom=2),
        )

    def test_no_bars(self):
        self.assertEqual(detect_letterbox(self.frame(20, 10, (0, 0, 0, 0))), Insets())

    def test_all_black_frame_refuses_to_guess(self):
        black = [[[0, 0, 0] for _ in range(8)] for _ in range(8)]
        self.assertEqual(detect_letterbox(black), Insets())

    def test_threshold_tolerates_near_black(self):
        f = self.frame(20, 10, (4, 0, 4, 0))
        for y in range(10):
            for x in list(range(4)) + list(range(16, 20)):
                f[y][x] = [9, 9, 9]
        self.assertEqual(detect_letterbox(f, threshold=12).left, 4)
        self.assertEqual(detect_letterbox(f, threshold=5).left, 0)


class TestDistance(unittest.TestCase):
    def test_normalized_distance(self):
        self.assertAlmostEqual(dist_n(0.0, 0.0, 0.3, 0.4), 0.5)


if __name__ == "__main__":
    unittest.main()
