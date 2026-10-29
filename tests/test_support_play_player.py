import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import support_players as sp
from rdom.input.inject import cell_uv
from rdom.perception.gear import UI

BUTTONS = [(0.13, 0.941), (0.35, 0.941), (0.57, 0.941), (0.79, 0.941)]


def board(spec):
    """spec: {cell: (type, pip)}; every other cell is Growth 1. None -> empty."""
    out = []
    for c in range(1, 16):
        v = spec.get(c, ("Growth", 1))
        out.append({"cell": c, "type": "empty", "variant": "empty", "pip": 0, "conf": 1.0}
                   if v is None else {"cell": c, "type": v[0], "variant": v[0], "pip": v[1], "conf": 1.0})
    return out


MERGE = {1: ("Resonance", 3), 2: ("Resonance", 3)}          # the only possible merge: 1 -> 2
SUPPORT = {5: ("Adjust", 7)}                                 # no merge; the supporter picks cell 5
COMPLETE = {**{c: ("Resonance", 7) for c in (1, 2)}, **{c: ("Alignment", 7) for c in (3, 4, 5)},
            **{c: ("Bubble", 1) for c in (6, 7)}}


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
        self.clear = True

    def grab(self):
        self.n += 1
        return self.n

    def window_moved(self):
        return self.moved

    def unobscured(self):
        return self.clear


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
    def burst(self, *a, **kw):
        return None

    def cells(self, *a, **kw):
        pass

    def frame(self, *a, **kw):
        pass


class FakePerception:
    def __init__(self, spec=None, close_after=1):
        self.board = board(spec or {})
        self.buffed = set()
        self.panel = False
        self.close_after, self.closes = close_after, 0
        self.show_banner = False
        self.kinds = {}                                     # banner text -> effect kind
        self.text = ""
        self.banner_texts = 0
        self.pip_sources = []
        self.ui_extra = {}

    def is_game_over(self, f):
        return False

    def tactic_sp1000_card(self, f):
        return None

    def ui_state(self, f):
        return {"hunt_popup": False, "hunt": False, "power_panel": self.panel,
                "transcend": False, "hpsp": False, **self.ui_extra}

    def is_battle(self, f):
        return True

    def buffed_cells(self, f):
        return self.buffed

    def board_glare(self, f):
        return False

    def power_buttons(self, f):
        return BUTTONS

    def banner_present(self, f):
        return self.show_banner

    def read_score(self, f):
        return None

    def power_cards(self, f):
        return {}                    # no card found: the visit only closes

    def banner_text(self, f):
        self.banner_texts += 1
        return self.text

    def effect_kind(self, text):
        return self.kinds.get(text)

    def read_cells_support(self, f, cells, pip_source="auto"):
        return [{"cell": c, "type": "junk", "variant": "junk", "pip": 0, "conf": 1.0} for c in cells]

    def frames_equal(self, a, b):
        return a == b

    def read_board_support(self, f, pip_source="auto"):
        self.pip_sources.append(pip_source)
        return [dict(d) for d in self.board]

    def on_tap(self, uv):
        if uv == UI["power_close"]:
            self.closes += 1
            if self.closes >= self.close_after:
                self.panel = False


@pytest.fixture(autouse=True)
def no_fail_crops(monkeypatch):
    monkeypatch.setattr(sp.collect, "save_fail", lambda f, a, b: None)


def make(spec=None, trial=False, tick=0.6, close_after=1):
    clock = FakeClock()
    perc = FakePerception(spec, close_after)
    g, inj = FakeGrabber(), FakeInjector(perc.on_tap)
    p = sp.PlayPlayer(g, inj, FakeSaver(), perc=perc, game_id="G", clock=clock, sleep=clock.sleep,
                      tick=tick, trial=trial)
    return p, g, inj, perc, clock


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def test_merge_needs_two_identical_reads():
    p, g, inj, perc, clock = make(MERGE)
    ticks(p, 1)
    assert inj.swipes == []                                 # first read: not confirmed
    ticks(p, 1)
    assert inj.swipes == [(*cell_uv(1), *cell_uv(2))]


def test_changing_read_resets_confirmation():
    p, g, inj, perc, clock = make(MERGE)
    ticks(p, 1)
    perc.board = board({**MERGE, 9: ("Growth", 2)})
    ticks(p, 1)
    assert inj.swipes == []                                 # the board changed between reads
    ticks(p, 1)
    assert len(inj.swipes) == 1


def test_buffed_cell_needs_four_reads():
    p, g, inj, perc, clock = make(MERGE)
    perc.buffed = {2}
    ticks(p, 3)
    assert inj.swipes == []
    ticks(p, 1)
    assert len(inj.swipes) == 1


def test_buffed_cell_unsteady_blocks():
    p, g, inj, perc, clock = make(MERGE)
    perc.buffed = {2}
    ticks(p, 3)
    perc.board = board({1: ("Resonance", 3), 2: ("Resonance", 3), 3: ("Growth", 2)})
    ticks(p, 2)                                             # sig stable again, cell 2 held 4 reads
    assert len(inj.swipes) == 1
    p2, g2, inj2, perc2, _ = make({1: ("Resonance", 3), 2: ("Resonance", 3)})
    perc2.buffed = {2}
    ticks(p2, 2)
    perc2.board = board({1: ("Resonance", 3), 2: ("Resonance", 3)})
    p2._hist[2] = [("Resonance", 3), ("Resonance", 4), ("Resonance", 3), ("Resonance", 3)]
    ticks(p2, 1)
    assert inj2.swipes == []                                # four reads but not identical


def test_buffed_supporter_needs_four_reads():
    p, g, inj, perc, clock = make(SUPPORT)
    perc.buffed = {5}
    ticks(p, 3)
    assert inj.swipes == []
    ticks(p, 1)
    assert len(inj.swipes) == 1


def test_junk_blocks_every_board_action():
    spec = {c: ("junk", 0) for c in (1, 2, 3, 4)}
    spec[10] = None                                         # an empty cell would normally summon
    p, g, inj, perc, clock = make(spec)
    ticks(p, 6)
    assert inj.taps == [] and inj.swipes == []
    spec3 = {c: ("junk", 0) for c in (1, 2, 3)}
    spec3[10] = None
    p, g, inj, perc, clock = make(spec3)
    ticks(p, 2)
    assert inj.taps == [UI["summon"]] * 2                   # 3 junk cells are tolerated


def swipes_of(inj, a, b):
    return [s for s in inj.swipes if s == (*cell_uv(a), *cell_uv(b))]


def test_no_effect_merge_is_banned(capsys, monkeypatch):
    fails = []
    monkeypatch.setattr(sp.collect, "save_fail", lambda f, a, b: fails.append((a["cell"], b["cell"])))
    p, g, inj, perc, clock = make(MERGE)
    ticks(p, 3)                                             # swipe on tick 2, verified on tick 3
    out = capsys.readouterr().out
    assert "merge 1->2 had no effect -> banned until those dice change" in out
    assert p.stats["fails"] == 1 and fails == [(1, 2)]
    ticks(p, 10)
    assert len(swipes_of(inj, 1, 2)) == 1                   # banned: not retried
    perc.board = board({1: ("Adjust", 3), 2: ("Resonance", 3)})
    ticks(p, 2)
    assert len(swipes_of(inj, 1, 2)) == 2                   # a die's type changed -> ban lifted


def test_pip_flicker_keeps_ban():
    p, g, inj, perc, clock = make(MERGE)
    ticks(p, 3)
    perc.board = board({1: ("Resonance", 2), 2: ("Resonance", 2)})   # same types, other pips
    ticks(p, 6)
    assert len(swipes_of(inj, 1, 2)) == 1


def test_ban_expires_after_90s():
    p, g, inj, perc, clock = make(MERGE)
    ticks(p, 12)
    assert len(swipes_of(inj, 1, 2)) == 1
    clock.t += 91
    ticks(p, 3)
    assert len(swipes_of(inj, 1, 2)) == 2


def test_fail_crop_not_saved_when_window_covered(capsys, monkeypatch):
    fails = []
    monkeypatch.setattr(sp.collect, "save_fail", lambda f, a, b: fails.append(1))
    p, g, inj, perc, clock = make(MERGE)
    g.clear = False
    ticks(p, 3)
    assert fails == [] and p.stats["fails"] == 1
    assert "frame not saved: game window covered" in capsys.readouterr().out


def test_summon_gap():
    p, g, inj, perc, clock = make({1: None}, tick=0.3)
    times = []
    inj.on_tap = lambda uv: times.append(clock())
    ticks(p, 20)                                            # 6 s
    assert 8 <= len(times) <= 12
    assert all(b - a >= 0.5 for a, b in zip(times, times[1:]))
    assert set(inj.taps) == {UI["summon"]}


def test_supporter_cooldown_and_line(capsys):
    p, g, inj, perc, clock = make(SUPPORT)
    ticks(p, 2)
    assert inj.swipes == [(*cell_uv(5), *UI["support"])]
    assert "Gr1 Gr1 Gr1 Gr1 Ad7" in capsys.readouterr().out
    ticks(p, 100)                                           # 60 s
    assert len(inj.swipes) == 1
    clock.t += 71                                           # > 130 s since the swipe
    ticks(p, 1)
    assert len(inj.swipes) == 2
    assert p.stats["support"] == 2


def test_log_lines_and_stats(capsys):
    p, g, inj, perc, clock = make({**MERGE, 3: None})
    ticks(p, 2)                                             # empty cell: summon, then merge confirmed
    perc.board = board(MERGE)
    ticks(p, 2)
    out = capsys.readouterr().out
    assert " | R7 0 L7 0 B0 -> merge 1->2" in out
    assert "Re3 Re3 Gr1" in out
    assert p.stats["merges"] == 1


def test_supporter_line_format(capsys):
    p, g, inj, perc, clock = make(SUPPORT)
    ticks(p, 2)
    assert " -> supporter <- 5" in capsys.readouterr().out
    assert p.stats["support"] == 1


def test_complete_and_forbidden_taps():
    p, g, inj, perc, clock = make(COMPLETE)
    perc.ui_extra = {"hpsp": True, "transcend": True}
    assert p.stats["complete"] is False
    ticks(p, 5)
    assert p.stats["complete"] is True
    assert UI["hpsp"] not in inj.taps and UI["transcend"] not in inj.taps
    assert not set(inj.taps) & set(BUTTONS)


def _banner_player(kind, text="t"):
    p, g, inj, perc, clock = make(SUPPORT)
    perc.show_banner, perc.text, perc.kinds = True, text, {text: kind}
    return p, perc, clock


def test_banner_ocr_every_3s():
    p, perc, clock = _banner_player("summon_bonus_when_short")
    ticks(p, 20)                                            # 12 s
    assert 4 <= perc.banner_texts <= 5


def test_clone_banner_arms_clone_alert_for_45s(monkeypatch):
    seen = []
    real = sp.plan_support

    def spy(*a, **kw):
        seen.append(kw["clone_alert"])
        return real(*a, **kw)
    monkeypatch.setattr(sp, "plan_support", spy)
    p, perc, clock = _banner_player("destroy3_clone_max")
    ticks(p, 2)                                             # banner read on tick 1
    assert p.clone_until == p._ocr_last + 45.0
    perc.show_banner = False
    clock.t += 30
    ticks(p, 1)
    clock.t += 16
    ticks(p, 1)                                             # > 45 s after the banner
    assert seen[0] is True and seen[1] is True and seen[-1] is False


def test_power_hold_banner_sets_deadline():
    p, perc, clock = _banner_player("sp_double_later")
    ticks(p, 1)
    assert p.hold_power_until == clock() + 65.0


def test_summon_bonus_banner_changes_nothing():
    p, perc, clock = _banner_player("summon_bonus_when_short")
    ticks(p, 3)
    assert p.clone_until < 0 and p.hold_power_until < 0
    assert {k: p.stats[k] for k in ("merges", "fails", "support", "complete")} == {
        "merges": 0, "fails": 0, "support": 1, "complete": False}


def test_trial_pip_source():
    for trial, want in ((True, "gear"), (False, "auto")):
        p, g, inj, perc, clock = make(MERGE, trial=trial)
        ticks(p, 2)
        assert set(perc.pip_sources) == {want}
        assert len(inj.swipes) == 1                         # same tick rules in both modes


def test_panel_hook_closes_only():
    p, g, inj, perc, clock = make(MERGE, close_after=2)
    perc.panel = True
    ticks(p, 1)
    assert inj.taps == [UI["power_close"]] * 2
    assert not set(inj.taps) & set(BUTTONS)
    assert inj.swipes == []


def test_panel_close_capped_at_4():
    p, g, inj, perc, clock = make(MERGE, close_after=99)
    perc.panel = True
    ticks(p, 1)
    assert inj.taps.count(UI["power_close"]) == 4
    assert not set(inj.taps) & set(BUTTONS)


def test_no_loop_modules_imported():
    for name in ("tools.gear_loop", "tools.run_all", "tools.supervisor", "tools.discord_bot",
                 "gear_loop", "run_all", "supervisor", "discord_bot"):
        assert name not in sys.modules
