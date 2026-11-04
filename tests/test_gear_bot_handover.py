import importlib.util
import os

import pytest

from rdom.perception import support

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "gear_bot.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("gear_bot_under_test", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeGrabber:
    def __init__(self):
        self.grabs = 0

    def window_moved(self):
        return False

    def grab(self):
        self.grabs += 1
        return object()


class FakeInj:
    execute = False

    def __init__(self):
        self.taps = []

    def tap(self, *uv):
        self.taps.append(uv)


@pytest.fixture
def bot(monkeypatch):
    m = load_tool()
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m, "is_game_over", lambda f: False)
    return m


def test_handover_on_first_tick_before_any_other_rule(bot, monkeypatch, capsys):
    monkeypatch.setattr(support, "detect_support_deck", lambda f: True)
    # any later rule would blow up: the hand-over must come first
    import rdom.perception.gear as gp

    def boom(*a, **k):
        raise AssertionError("rule ran before the hand-over")
    monkeypatch.setattr(gp, "tactic_sp1000_card", boom)
    monkeypatch.setattr(gp, "ui_state", boom)
    inj = FakeInj()
    assert bot.play(FakeGrabber(), inj, minutes=1) == "wrong_deck"
    assert "support deck seen in gear bot -- handing over" in capsys.readouterr().out
    assert inj.taps == []


def test_detect_runs_on_first_tick_then_every_10s(bot, monkeypatch):
    calls = []
    monkeypatch.setattr(support, "detect_support_deck", lambda f: calls.append(1) or False)
    clock = {"t": 1000.0}
    monkeypatch.setattr(bot.time, "monotonic", lambda: clock["t"])
    import rdom.perception.gear as gp

    class Stop(Exception):
        pass

    def tick_end(*a, **k):
        clock["t"] += 4.0                       # 4 s per tick
        if clock["t"] > 1000.0 + 25:
            raise Stop
        return (0.5, 0.5)                       # a tactic card: the tick ends with `continue`
    monkeypatch.setattr(gp, "tactic_sp1000_card", tick_end)
    with pytest.raises(Stop):
        bot.play(FakeGrabber(), FakeInj(), minutes=10)
    # ticks at t=1000 (first), 1004, 1008, 1012 (>=10 s), 1016, 1020, 1024 (>=10 s)
    assert len(calls) == 3


# ---- rdT10: an unconfirmed merge swipe is retried, not banned
class SwipeInj(FakeInj):
    def __init__(self, ok):
        super().__init__()
        self.swipes, self.last_gesture_ok = [], ok

    def swipe(self, *a, **kw):
        self.swipes.append(a)


class _Ui(dict):
    def __missing__(self, k):
        return False


def _run_unchanged_board(bot, monkeypatch, ok, ticks=6):
    import rdom.perception.gear as gp
    cells = [{"cell": c, "type": "Growth", "variant": "Growth", "pip": 1} for c in range(1, 16)]
    n = [0]

    def over(f):
        n[0] += 1
        return n[0] > ticks
    monkeypatch.setattr(bot, "is_game_over", over)
    monkeypatch.setattr(support, "detect_support_deck", lambda f: False)
    monkeypatch.setattr(gp, "tactic_sp1000_card", lambda f: None)
    monkeypatch.setattr(gp, "detect_deck", lambda f: None)
    monkeypatch.setattr(bot, "ui_state", lambda f: _Ui())
    monkeypatch.setattr(bot, "is_battle", lambda f: True)
    monkeypatch.setattr(bot, "read_board", lambda f: [dict(d) for d in cells])
    monkeypatch.setattr(bot, "buffed_cells", lambda f: set())
    monkeypatch.setattr(bot, "banner_present", lambda f: False)
    monkeypatch.setattr(bot.collect, "maybe_save", lambda *a, **k: None)
    fails = []
    monkeypatch.setattr(bot.collect, "save_fail", lambda *a, **k: fails.append(a))
    monkeypatch.setattr(bot, "evaluate", lambda b: {"complete": False, "empty": 0, "unknown": 0, "gears": 0,
                                                    "kept": {}, "largest_cluster": 0, "gear_avg": 0})
    seen_banned = []

    def plan(b, banned=(), **k):
        seen_banned.append(set(banned))
        return {"op": "wait", "why": "banned"} if (1, 2) in banned else {"op": "merge", "from": 1, "to": 2}
    monkeypatch.setattr(bot, "plan_next", plan)
    inj = SwipeInj(ok)
    assert bot.play(FakeGrabber(), inj, minutes=1) == "game_over"
    return inj, fails, seen_banned


def test_unconfirmed_merge_swipe_is_not_banned_and_retried(bot, monkeypatch, capsys):
    inj, fails, seen_banned = _run_unchanged_board(bot, monkeypatch, ok=False)
    out = capsys.readouterr().out
    assert "merge 1->2 not confirmed in front -- retry" in out and "had no effect" not in out
    assert fails == [] and bot.play.stats["fails"] == 0
    assert all(not b for b in seen_banned) and len(inj.swipes) >= 2


def test_confirmed_unchanged_merge_is_still_banned(bot, monkeypatch, capsys):
    inj, fails, _ = _run_unchanged_board(bot, monkeypatch, ok=True)
    assert "merge 1->2 had no effect -> banned until those dice change" in capsys.readouterr().out
    assert len(fails) == 1 and bot.play.stats["fails"] == 1
