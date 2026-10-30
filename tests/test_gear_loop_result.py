"""gear_loop (rdf03-m1): importing it is side-effect free; after_battle driven with fakes."""
import importlib
import sys
import time

import pytest


@pytest.fixture
def gl(monkeypatch):
    """Import tools.gear_loop with the live entry points booby-trapped, then drop it from
    sys.modules again (other tests assert the loop modules were never imported)."""
    import rdom.capture.live as live
    import rdom.input.inject as inject
    import rdom.notify.discord as discord

    def boom(*a, **k):
        raise AssertionError("live side effect at import")

    monkeypatch.setattr(live, "place_game_window", boom)
    monkeypatch.setattr(live, "LiveGrabber", boom)
    monkeypatch.setattr(inject, "Injector", boom)
    monkeypatch.setattr(discord, "send_status", boom)
    for n in ("tools.gear_loop", "gear_loop"):
        monkeypatch.delitem(sys.modules, n, raising=False)
    t0 = time.monotonic()
    mod = importlib.import_module("tools.gear_loop")
    assert time.monotonic() - t0 < 30
    # AI-NOTE: plain pop, not monkeypatch.delitem -- that would restore the module at teardown
    sys.modules.pop("tools.gear_loop", None)
    return mod


class FakeGrabber:
    def __init__(self):
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return "frame"


def run(gl, monkeypatch, res, battle, capsys):
    monkeypatch.setattr(gl.time, "sleep", lambda s: None)
    g, calls = FakeGrabber(), []
    stop = gl.after_battle(res, g, "inj", exit_fn=lambda g_, i: calls.append((g_, i)) or "ok",
                           battle_fn=lambda f: battle)
    return stop, g, calls, capsys.readouterr().out


def test_import_has_no_side_effects(gl):
    # the booby-trapped names did not fire; main() exists but was not run
    assert callable(gl.main) and callable(gl.after_battle)


@pytest.mark.parametrize("res", ["clear", "game_over"])
def test_result_exits_to_lobby_once(gl, monkeypatch, capsys, res):
    stop, g, calls, out = run(gl, monkeypatch, res, False, capsys)
    assert stop is False
    assert out.splitlines() == [f"battle result: {res}", "로비로 가기: ok"]
    assert calls == [(g, "inj")] and g.grabs == 1


@pytest.mark.parametrize("res", ["clear", "game_over"])
def test_battle_still_on_screen_does_not_exit(gl, monkeypatch, capsys, res):
    stop, g, calls, out = run(gl, monkeypatch, res, True, capsys)
    assert out.splitlines() == [f"battle result: {res}", "battle still on screen -- 로비로 가기 skipped"]
    assert calls == [] and g.grabs == 1


def test_moved_stops_loop_without_exit(gl, monkeypatch, capsys):
    stop, g, calls, out = run(gl, monkeypatch, "moved", False, capsys)
    assert stop is True and calls == [] and g.grabs == 0
    assert out.splitlines() == ["battle result: moved"]


def test_timeout_only_logs(gl, monkeypatch, capsys):
    stop, g, calls, out = run(gl, monkeypatch, "timeout", False, capsys)
    assert stop is False and calls == [] and g.grabs == 0
    assert out.splitlines() == ["battle result: timeout"]


def test_report_runs_between_result_line_and_exit(gl, monkeypatch, capsys):
    monkeypatch.setattr(gl.time, "sleep", lambda s: None)
    order = []
    gl.after_battle("clear", FakeGrabber(), "inj", exit_fn=lambda g, i: order.append("exit"),
                    battle_fn=lambda f: False, report=lambda: order.append("report"))
    assert order == ["report", "exit"]
