from rdom.recorder.geometry import Insets, Rect, fit_chrome


def _client(w, h):
    return Rect(left=100, top=0, right=100 + w, bottom=h)


def test_sidebar_shown_keeps_measured_inset():
    # 2026-09-16 calibration: client 1200x2104, tab bar 40, sidebar 39 -> 1161x2064
    ch = fit_chrome(_client(1200, 2104), Insets(top=40, right=39))
    assert ch.right == 39


def test_sidebar_hidden_drops_right_inset():
    # 2026-10-07: client 1158x2099, sidebar hidden -> full 1158 width is game
    ch = fit_chrome(_client(1158, 2099), Insets(top=40, right=39))
    assert ch.right == 0
    assert ch.top == 40
