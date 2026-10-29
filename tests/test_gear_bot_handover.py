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
