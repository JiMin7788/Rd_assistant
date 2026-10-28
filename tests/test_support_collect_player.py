import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_players as sp
from rdom.perception.gear import UI

BUTTONS = [(0.13, 0.941), (0.35, 0.941), (0.57, 0.941), (0.79, 0.941)]


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeGrabber:
    def __init__(self):
        self.n = 0
        self.moved = False

    def grab(self):
        self.n += 1
        return self.n

    def window_moved(self):
        return self.moved


class FakeInjector:
    execute = True

    def __init__(self, on_tap=None):
        self.taps, self.swipes, self.on_tap = [], [], on_tap

    def tap(self, u, v):
        self.taps.append((u, v))
        if self.on_tap:
            self.on_tap((u, v))

    def swipe(self, *a, **kw):
        self.swipes.append(a)


class FakeSaver:
    def __init__(self):
        self.cells_calls, self.frame_calls = [], []

    def cells(self, frame, game_id, t, **kw):
        self.cells_calls.append((frame, game_id, t, kw))

    def frame(self, frame, path):
        self.frame_calls.append((frame, path))


class FakePerception:
    """Scripted per tick: `script(frame_no)` -> dict of overrides; panel is state-driven."""

    def __init__(self, script=None, close_after=1):
        self.script = script or (lambda n: {})
        self.panel = False
        self.panel_next = False
        self.close_after = close_after
        self.closes = 0
        self.ui_calls = 0

    def _s(self, f):
        return self.script(f)

    def is_game_over(self, f):
        return self._s(f).get("over", False)

    def tactic_sp1000_card(self, f):
        return self._s(f).get("card")

    def ui_state(self, f):
        s = self._s(f)
        if self.panel_next:
            self.panel, self.panel_next = True, False
        return {"hunt_popup": s.get("popup", False), "hunt": s.get("hunt", False),
                "power_panel": self.panel or s.get("panel", False),
                "transcend": False, "hpsp": False}

    def is_battle(self, f):
        return self._s(f).get("battle", True)

    def buffed_cells(self, f):
        return {3, 4}

    def board_glare(self, f):
        return True

    def power_buttons(self, f):
        return BUTTONS

    # world model: taps change the panel
    def on_tap(self, uv):
        if uv == UI["power_open"]:
            self.panel_next = True
        elif uv == UI["power_close"]:
            self.closes += 1
            if self.closes >= self.close_after:
                self.panel = False


class Probe(sp.BasePlayer):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events = []

    def on_panel(self, f, ui, now):
        self.events.append("panel")

    def battle_tick(self, f, ui, now):
        self.events.append("battle")


def make(cls, script=None, close_after=1, tick=0.5):
    clock = FakeClock()
    perc = FakePerception(script, close_after)
    g, inj, saver = FakeGrabber(), FakeInjector(perc.on_tap), FakeSaver()
    p = cls(g, inj, saver, perc=perc, game_id="G", clock=clock, sleep=clock.sleep, tick=tick)
    return p, g, inj, saver, perc, clock


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def test_window_moved(capsys):
    p, g, inj, *_ = make(Probe)
    g.moved = True
    assert p.run(1) == "moved"
    assert "window moved -- stopping" in capsys.readouterr().out
    assert inj.taps == [] and p.events == []


def test_game_over(capsys):
    p, g, inj, *_ = make(Probe, lambda n: {"over": n >= 3})
    assert p.run(1) == "game_over"
    assert "game over" in capsys.readouterr().out


def test_tactic_card_one_tap():
    p, g, inj, *_ = make(Probe, lambda n: {"card": (0.5, 0.494), "hunt": True, "popup": True} if n == 1 else {"battle": False})
    ticks(p, 1)
    assert inj.taps == [(0.5, 0.494)]
    assert p.events == []


def test_hunt_popup_tap():
    p, g, inj, *_ = make(Probe, lambda n: {"popup": True, "hunt": True})
    ticks(p, 1)
    assert inj.taps == [UI["hunt_popup_ok"]]


def test_panel_hook_before_hunt():
    p, g, inj, *_ = make(Probe, lambda n: {"panel": True, "hunt": True})
    ticks(p, 1)
    assert p.events == ["panel"]
    assert inj.taps == []                         # the hook ran, the hunt rule did not


def test_hunt_every_3s():
    p, g, inj, *_ = make(Probe, lambda n: {"hunt": True})
    times = []
    inj.on_tap = lambda uv: times.append(p.clock())
    p.run(0.2)                                    # 12 s
    assert len(times) >= 4
    assert all(b - a >= 3.0 for a, b in zip(times, times[1:]))
    assert set(inj.taps) == {UI["hunt"]}
    assert len(p.events) == 24 - len(times)       # a hunt tick never falls through to battle_tick


def test_non_battle_never_reaches_battle_tick():
    p, g, inj, saver, *_ = make(Probe, lambda n: {"battle": False})
    p.run(0.5)
    assert p.events == [] and saver.cells_calls == [] and saver.frame_calls == []


def test_data_cadence():
    p, g, inj, saver, perc, clock = make(Probe)
    p.run(100 / 60)                               # 100 s
    assert [c[2] for c in saver.cells_calls] == [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0]
    _, gid, _, kw = saver.cells_calls[0]
    assert gid == "G" and kw == {"buffed": {3, 4}, "glare": True}
    assert [c[1] for c in saver.frame_calls] == [
        "data/support_frames/G/0.0.png", "data/support_frames/G/30.0.png",
        "data/support_frames/G/60.0.png", "data/support_frames/G/90.0.png"]


def test_collect_200s_summon_only():
    p, g, inj, saver, perc, clock = make(sp.CollectPlayer)
    times = []
    inj.on_tap = lambda uv: (perc.on_tap(uv), times.append((clock(), uv)))
    assert p.run(200 / 60) == "timeout"
    summons = [t for t, uv in times if uv == UI["summon"]]
    assert len(summons) > 100
    assert all(b - a >= 1.0 for a, b in zip(summons, summons[1:]))
    assert inj.swipes == []
    assert UI["hpsp"] not in inj.taps and UI["transcend"] not in inj.taps
    assert not set(inj.taps) & set(BUTTONS)


def test_panel_snapshot_once():
    p, g, inj, saver, perc, clock = make(sp.CollectPlayer, close_after=2)
    p.run(300 / 60)
    assert inj.taps.count(UI["power_open"]) == 1
    panel = [c[1] for c in saver.frame_calls if "panel_" in c[1]]
    assert len(panel) == 1
    assert panel[0].startswith("data/support_frames/G/panel_12") and panel[0].endswith(".png")
    assert inj.taps.count(UI["power_close"]) == 2     # until ui_state reported the panel closed


def test_panel_close_capped_at_4():
    p, g, inj, saver, perc, clock = make(sp.CollectPlayer, close_after=99)
    ticks(p, 242)                                     # tick 241 opens (t=120), tick 242 sees the panel
    assert inj.taps.count(UI["power_open"]) == 1
    assert inj.taps.count(UI["power_close"]) == 4     # the panel never closes: capped per visit


def test_stray_panel_closed_without_saving():
    p, g, inj, saver, perc, clock = make(sp.CollectPlayer, lambda n: {"panel": 40 <= n < 42})
    perc.close_after = 1
    p.run(30 / 60)                                    # well before 120 s
    assert inj.taps.count(UI["power_close"]) >= 1
    assert not [c for c in saver.frame_calls if "panel_" in c[1]]
    assert UI["power_open"] not in inj.taps


def test_timeout_and_stats():
    p, g, inj, saver, perc, clock = make(sp.CollectPlayer)
    assert p.run(0.5) == "timeout"
    assert clock() >= 1000.0 + 30
    assert p.stats == {"merges": 0, "fails": 0, "support": 0, "complete": False}
