"""gear_bot.play() opening phase (rdT13): faster summoning until the first merge. All input is faked."""
import importlib.util
import os

import pytest

from rdom.perception import collect, support
import rdom.perception.gear as gp

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "gear_bot.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("gear_bot_opening_under_test", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Run:
    """Fake grabber + injector + clock; `script` = one (op, empty cells) per loop, then the window 'moves'."""

    def __init__(self, bot, monkeypatch, script):
        self.script, self.loop, self.events, self.clock = script, 0, [], 1000.0
        self.planned = 0
        monkeypatch.setattr(bot.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(bot.time, "sleep", self.sleep)
        monkeypatch.setattr(bot, "is_game_over", lambda f: False)
        monkeypatch.setattr(bot, "is_battle", lambda f: True)
        monkeypatch.setattr(bot, "banner_present", lambda f: False)
        monkeypatch.setattr(bot, "buffed_cells", lambda f: set())
        monkeypatch.setattr(bot, "ui_state", lambda f: dict(hunt_popup=False, transcend=False,
                                                             power_panel=False, hpsp=False, hunt=False))
        monkeypatch.setattr(bot, "read_board", self.read_board)
        monkeypatch.setattr(bot, "evaluate", self.evaluate)
        monkeypatch.setattr(bot, "plan_next", self.plan_next)
        monkeypatch.setattr(support, "detect_support_deck", lambda f, **k: False)
        monkeypatch.setattr(gp, "tactic_sp1000_card", lambda f: None)
        monkeypatch.setattr(gp, "detect_deck", lambda f: None)
        monkeypatch.setattr(collect, "maybe_save", lambda *a, **k: None)
        monkeypatch.setattr(collect, "save_fail", lambda *a, **k: None)
        self.bot = bot

    # --- fake grabber
    def window_moved(self):
        self.loop += 1
        return self.loop > len(self.script)

    def grab(self):
        return object()

    # --- fake injector
    execute = False
    last_gesture_ok = True

    def tap(self, *uv):
        self.events.append(("tap", uv == tuple(self.bot.UI["summon"]), self.clock))

    def swipe(self, *a, **k):
        self.events.append(("swipe", a[-2:] == tuple(self.bot.UI["support"]), self.clock))

    def sleep(self, s):
        self.events.append(("sleep", s))
        self.clock += s

    # --- recognition fakes
    def read_board(self, f):
        # cell 1's pip changes every loop so a merge on it always reads as "took effect"
        return [dict(cell=c, type="Fire", pip=self.loop if c == 1 else 1, variant=0) for c in range(1, 16)]

    def evaluate(self, b):
        return dict(complete=False, empty=self.script[self.loop - 1][1], unknown=0, gears=0, kept={},
                    gear_avg=0, largest_cluster=0)

    def plan_next(self, b, **k):
        op = self.script[self.loop - 1][0]
        return dict(op=op, **({"from": 1, "to": 2} if op in ("merge", "support") else {}))

    def play(self, tick=0.6):
        return self.bot.play(self, self, minutes=10, tick=tick)

    def summon_taps(self):
        return [e for e in self.events if e[0] == "tap" and e[1]]

    def sleeps(self):
        return [e[1] for e in self.events if e[0] == "sleep"]


@pytest.fixture
def bot():
    return load_tool()


def test_opening_burst_taps_all_empty_cells(bot, monkeypatch):
    r = Run(bot, monkeypatch, [("summon", 4)])
    assert r.play() == "moved"
    assert len(r.summon_taps()) == 4


def test_opening_burst_capped_at_five(bot, monkeypatch):
    r = Run(bot, monkeypatch, [("summon", 9)])
    r.play()
    assert len(r.summon_taps()) == 5


def test_opening_sleeps_and_burst_gap(bot, monkeypatch):
    r = Run(bot, monkeypatch, [("summon", 4)])
    r.play(tick=0.6)
    assert bot.OPENING_TICK == 0.2 and bot.OPENING_SUMMON_GAP == 0.12 and bot.OPENING_BURST_MAX == 5
    assert r.sleeps()[:4] == [0.2, 0.12, 0.12, 0.12]
    times = [e[2] for e in r.summon_taps()]
    assert all(abs((b - a) - 0.12) < 1e-9 for a, b in zip(times, times[1:]))


def test_after_first_merge_normal_tick_and_single_gapped_tap(bot, monkeypatch, capsys):
    r = Run(bot, monkeypatch, [("summon", 3), ("merge", 1)] + [("summon", 3)] * 4)
    r.play(tick=0.3)
    sl = r.sleeps()
    assert sl[-4:] == [0.3] * 4                       # normal tick once the opening is over
    assert sl.count(0.2) == 2                         # loops 1 and 2 (the merge loop) were opening loops
    post = [e for e in r.events[r.events.index(next(e for e in r.events if e[0] == "swipe")):]
            if e[0] == "tap"]
    assert len(post) == 2                             # 4 loops 0.3 s apart, SUMMON_GAP 0.5 -> every 2nd loop
    assert post[1][2] - post[0][2] == pytest.approx(0.6)


def test_after_first_merge_default_tick_one_tap_per_loop(bot, monkeypatch):
    r = Run(bot, monkeypatch, [("merge", 1)] + [("summon", 9)] * 3)
    r.play(tick=0.6)
    assert len(r.summon_taps()) == 3


def test_support_swipe_does_not_end_opening(bot, monkeypatch, capsys):
    r = Run(bot, monkeypatch, [("support", 1), ("summon", 4)])
    r.play()
    assert bot.play.stats["merges"] == 0 and bot.play.stats["support"] == 1
    assert len(r.summon_taps()) == 4                  # still a burst
    assert r.sleeps()[0] == 0.2 and r.sleeps()[1] == 0.2
    assert "opening done" not in capsys.readouterr().out


def test_opening_done_line_once(bot, monkeypatch, capsys):
    r = Run(bot, monkeypatch, [("summon", 4), ("merge", 1), ("merge", 1), ("summon", 2)])
    r.play()
    out = capsys.readouterr().out
    assert out.count("opening done") == 1
    assert "opening done: 4 summon taps in 0.8 s" in out
