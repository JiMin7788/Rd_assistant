import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
import support_bot as sb
import support_players as sp
from rdom.perception.gear import UI
from rdom.policy.milestones import MilestoneTracker
from rdom.policy.power import PowerConfig, PowerTracker
from test_support_play_player import (COMPLETE, BUTTONS, FakeClock, FakeGrabber, FakeInjector,
                                      FakePerception, board)

CARDS = {"Growth": (0.13, 0.9), "Alignment": (0.35, 0.9), "Resonance": (0.57, 0.9)}


class RecSaver:
    """Records every frame save; `ret` is what a covered window would return (None)."""

    def __init__(self, covered=False, log=None):
        self.saved, self.covered, self.log = [], covered, log

    def cells(self, *a, **kw):
        pass

    def frame(self, frame, path):
        self.saved.append((frame, path))
        if self.log is not None:
            self.log.append(("frame", path))
        return None if self.covered else path


def nxt(seq):
    """Scripted reads: pop while more than one is left, the last one repeats; empty -> None."""
    if not seq:
        return None
    return seq.pop(0) if len(seq) > 1 else seq[0]


class PowerPerception(FakePerception):
    def __init__(self, spec=None, close_after=1):
        super().__init__(spec, close_after)
        self.cards = dict(CARDS)
        self.levels = {"Growth": [7], "Alignment": [1], "Resonance": [1]}   # card -> list of scripted reads (last one repeats)
        self.level_calls = []
        self.scores = []
        self.sps = [None]                                   # battle SP per read_sp call
        self.costs = [None]                                 # summon cost per read_summon_cost call
        self.panel_sps = [None]                             # panel SP per read_panel_sp call
        self.prices = {c: [None] for c in CARDS}            # card -> scripted price reads
        self.live = None                                    # not None: panel SP that drops by live_price per card tap
        self.live_price = 100

    def power_cards(self, f):
        return dict(self.cards)

    def card_level(self, f, button):
        self.level_calls.append((f, button))
        card = next(c for c, uv in CARDS.items() if uv == button)
        return nxt(self.levels[card])

    def read_score(self, f):
        return self.scores.pop(0) if len(self.scores) > 1 else (self.scores[0] if self.scores else None)

    def read_sp(self, f):
        return nxt(self.sps)

    def read_summon_cost(self, f):
        return nxt(self.costs)

    def read_panel_sp(self, f):
        return self.live if self.live is not None else nxt(self.panel_sps)

    def read_price(self, f, button_uv):
        card = next(c for c, uv in CARDS.items() if uv == button_uv)
        return self.live_price if self.live is not None else nxt(self.prices[card])

    def on_tap(self, uv):
        super().on_tap(uv)
        if self.live is not None and uv in CARDS.values():
            self.live -= self.live_price


def make(spec=None, trial=False, covered=False, close_after=1):
    clock = FakeClock()
    log = []
    perc = PowerPerception(spec, close_after)
    g = FakeGrabber()
    inj = FakeInjector(lambda uv: (log.append(("tap", uv)), perc.on_tap(uv)))
    saver = RecSaver(covered, log)
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock.sleep(s)

    p = sp.PlayPlayer(g, inj, saver, perc=perc, game_id="G", clock=clock, sleep=sleep, tick=0.6,
                      trial=trial, power_cfg=PowerConfig())
    p.sleeps, p.log = sleeps, log
    return p, g, inj, perc, saver, clock


def ticks(p, n):
    for _ in range(n):
        p.sleep(p.tick_s)
        p.tick()


def opens(inj):
    return inj.taps.count(UI["power_open"])


# ---- AC1 / AC2 SP trigger (R6) ---------------------------------------------------------------

def armed(sps=1000, costs=100, **kw):
    """A player whose SP and cost reads are scripted (keep = 3 x 100 = 300, no price known yet)."""
    p, g, inj, perc, saver, clock = make(**kw)
    perc.sps = sps if isinstance(sps, list) else [sps]
    perc.costs = costs if isinstance(costs, list) else [costs]
    return p, g, inj, perc, saver, clock


def test_trigger_opens_panel_with_exact_line(capsys):
    p, g, inj, perc, saver, clock = armed()
    ticks(p, 1)
    assert opens(inj) == 0                                  # the cost is not confirmed after one read
    ticks(p, 1)
    assert opens(inj) == 1
    assert "power-up (SP 1000 > keep 300)" in capsys.readouterr().out


def test_trigger_works_on_an_unstable_board():
    p, g, inj, perc, saver, clock = armed()
    ticks(p, 1)
    perc.board = board({1: ("Resonance", 3)})               # the board changes: not stable
    ticks(p, 1)
    assert opens(inj) == 1


def test_no_trigger_when_cost_unconfirmed():
    p, g, inj, perc, saver, clock = armed(costs=[100, 200, 100, 200, 100, 200])
    ticks(p, 6)
    assert opens(inj) == 0 and p.cost is None


def test_cost_is_kept_until_a_new_pair():
    p, g, inj, perc, saver, clock = armed(costs=[100, 100, 150, 200, 200])
    ticks(p, 3)
    assert p.cost == 100
    ticks(p, 2)
    assert p.cost == 200


@pytest.mark.parametrize("sps", [[1000, None], [None, 1000]])
def test_no_trigger_when_one_sp_read_is_none(sps):
    p, g, inj, perc, saver, clock = armed(sps=sps * 4)
    ticks(p, 6)
    assert opens(inj) == 0


def test_no_trigger_when_previous_sp_is_below():
    p, g, inj, perc, saver, clock = armed(sps=[299, 1000, 1000])
    ticks(p, 2)
    assert opens(inj) == 0                                  # previous read 299 < keep 300
    ticks(p, 1)
    assert opens(inj) == 1


def test_no_trigger_when_sp_below_keep_plus_last_price():
    p, g, inj, perc, saver, clock = armed(sps=499)
    p.power.confirmed("Growth", 200)                        # next card is still Growth: est 200
    ticks(p, 4)
    assert opens(inj) == 0
    perc.sps = [500]
    ticks(p, 2)
    assert opens(inj) == 1


def test_no_trigger_when_nothing_is_left_to_buy():
    p, g, inj, perc, saver, clock = armed()
    p.power._maxed.extend(["Growth", "Alignment", "Resonance"])
    ticks(p, 4)
    assert opens(inj) == 0


def test_trigger_gap_of_20s():
    p, g, inj, perc, saver, clock = armed()
    ticks(p, 2)
    assert opens(inj) == 1
    ticks(p, 30)                                            # 18 s later
    assert opens(inj) == 1
    ticks(p, 5)
    assert opens(inj) == 2


def test_no_trigger_before_hold_deadline():
    p, g, inj, perc, saver, clock = armed()
    p.hold_power_until = clock.t + 10.0                     # set by the sp_double_later banner
    ticks(p, 10)                                            # 6 s
    assert opens(inj) == 0
    ticks(p, 10)
    assert opens(inj) == 1


def test_no_trigger_while_a_merge_is_pending(monkeypatch):
    p, g, inj, perc, saver, clock = armed()
    p._pending = [1, 2, {}, 0]
    monkeypatch.setattr(p, "_verify_merge", lambda *a: None)
    ticks(p, 5)
    assert opens(inj) == 0


def test_no_trigger_when_junk_guard_fails():
    p, g, inj, perc, saver, clock = armed(spec={c: ("junk", 0) for c in (1, 2, 3, 4)})
    ticks(p, 5)
    assert opens(inj) == 0                                  # 4 raw unreadable cells > MAX_JUNK


def wait_plan(monkeypatch):
    monkeypatch.setattr(sp, "plan_support", lambda *a, **kw: {"op": "wait", "why": "test"})


def test_old_triggers_are_gone(monkeypatch):
    # no SP read at all: neither a complete board nor a 'wait' plan opens the panel
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 5)
    assert opens(inj) == 0
    wait_plan(monkeypatch)
    p, g, inj, perc, saver, clock = make()
    ticks(p, 5)
    assert opens(inj) == 0
    src = open(sp.__file__, encoding="utf-8").read()
    assert "power-up (complete)" not in src and "idle (" not in src


def test_trigger_gap_counts_from_the_visit():
    p, g, inj, perc, saver, clock = armed()
    ticks(p, 2)
    perc.panel = True
    ticks(p, 1)                                             # a visit (cost known, panel SP unreadable, closes)
    perc.panel = False
    n = opens(inj)
    ticks(p, 20)
    assert opens(inj) == n                                  # < 20 s since the visit


# ---- AC3 / AC4 / AC5 power visit (R7) ----------------------------------------------------------

def visit(p, perc, panel_sps=None, prices=None, cost=100):
    p.cost = cost
    if panel_sps is not None:
        perc.panel_sps = panel_sps
    for c, pr in (prices or {}).items():
        perc.prices[c] = pr
    perc.panel = True
    p.power_visit(1000)


def card_taps(inj):
    return [c for uv in inj.taps for c, cuv in CARDS.items() if cuv == uv]


P100 = {c: [100] for c in CARDS}
DROPPING = [1000, 1000, 900, 800, 700, 600, 500, 400, 300]    # panel SP: two reads, then one per tap


def test_visit_buys_in_order_and_stops_at_the_reserve(capsys):
    p, g, inj, perc, saver, clock = make()
    p.sleeps.clear()
    visit(p, perc, list(DROPPING), P100)
    # SP 1000 -> 300 with keep 300 and price 100: seven buys, an eighth would leave 200
    assert card_taps(inj) == ["Growth"] * 6 + ["Alignment"]
    assert inj.taps[-1] == UI["power_close"]
    assert p.log[0] == ("frame", "data/support_frames/G/panel_0.0.png")   # saved before any tap
    assert p.sleeps.count(0.3) == 1 and p.sleeps.count(0.5) == 7          # one reread, one confirm look per tap
    out = capsys.readouterr().out
    assert "Lv check: Growth read 7, count 1 (count kept)" in out
    assert "power panel -> GGGGGGA (7 bought), close (Lv G7 A2 R1, SP 300, keep 300)" in out
    assert p.power.levels() == {"Growth": 7, "Alignment": 2, "Resonance": 1}
    assert p.power.record()["src"] == "count"


def test_visit_levels_are_read_on_two_frames():
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, list(DROPPING), P100)
    frames = [f for f, _ in perc.level_calls]
    assert frames[:3] == [1000] * 3 and frames[3] != 1000 and frames[3:6] == [frames[3]] * 3


def test_visit_continues_the_order_across_visits():
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [450, 450, 400, 300], P100)
    assert card_taps(inj) == ["Growth"] * 2
    inj.taps.clear()
    visit(p, perc, [450, 450, 400, 300], P100)
    assert card_taps(inj) == ["Growth"] * 2
    assert p.power.levels()["Growth"] == 5


def test_visit_sp0_is_the_smaller_of_two_panel_reads(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [900, 350], P100)                        # min 350: 350 - 100 < keep 300
    assert card_taps(inj) == []
    assert "power panel: nothing to buy (SP 350, keep 300) -- closed" in capsys.readouterr().out


def test_visit_nothing_to_buy_line(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [399, 399], P100)
    assert "power panel: nothing to buy (SP 399, keep 300) -- closed" in capsys.readouterr().out
    assert card_taps(inj) == [] and inj.taps == [UI["power_close"]]


@pytest.mark.parametrize("sps", [[1000, None], [None]])
def test_visit_sp_unreadable(capsys, sps):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, sps, P100)
    assert "power panel: SP unreadable -- closed" in capsys.readouterr().out
    assert card_taps(inj) == [] and inj.taps == [UI["power_close"]]
    assert sum(s == sp.PANEL_SP_RETRY_WAIT for s in p.sleeps) == round(sp.PANEL_SP_RETRY_FOR / sp.PANEL_SP_RETRY_WAIT)


def test_visit_sp_popup_fades_then_reads(capsys):
    """A '+30' popup covers the panel SP on the first reads; later grabs read it and the visit goes on."""
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [None, None, 900, 1000], P100)
    out = capsys.readouterr().out
    assert "SP unreadable" not in out and "SP 900" in out    # sp0 is the lower of the two numbers read


@pytest.mark.parametrize("sps,shown", [([1000, 1000], "1000"), ([None], "?")])
def test_visit_with_unknown_keep_closes(capsys, sps, shown):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, sps, P100, cost=None)
    assert f"power panel: nothing to buy (SP {shown}, keep ?) -- closed" in capsys.readouterr().out
    assert card_taps(inj) == []


def test_visit_confirms_by_sp_drop_of_half_the_price(capsys):
    p, g, inj, perc, saver, clock = make()
    # first tap: SP 950 = 1000 - price/2 confirms; second tap: SP 951 > 950 - 50 does not
    visit(p, perc, [1000, 1000, 950, 951], P100)
    out = capsys.readouterr().out
    assert p.power.levels()["Growth"] == 2
    assert "power panel: Growth tap not confirmed (SP 950 -> 951)" in out
    assert "power panel -> Gg (1 bought), close (Lv G2 A1 R1, SP 950, keep 300)" in out


def test_visit_confirms_by_level_rise(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels["Growth"] = [1, 1, 2]                       # two reads at visit start, then a rise after the first tap
    visit(p, perc, [1000], P100)                            # SP never drops
    assert p.power.levels()["Growth"] == 2                  # first tap confirmed by the level alone
    assert p.power.last_price("Growth") == 100
    assert card_taps(inj) == ["Growth", "Growth"]           # the second tap shows no rise and no drop
    out = capsys.readouterr().out
    assert "power panel: Growth tap not confirmed (SP 900 -> 1000)" in out    # sp0 = 1000 - price, not the stale 1000
    assert "power panel -> Gg (1 bought), close (Lv G2 A1 R1, SP 900, keep 300)" in out


def test_visit_level_confirmed_tap_does_not_carry_stale_sp(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels["Growth"] = [1, 1, 2]
    visit(p, perc, [450], P100)                             # SP shows 450 after the tap too (stale)
    # 450 - 100 = 350 after the buy; a second buy would leave 250 < keep 300, so there is none
    assert card_taps(inj) == ["Growth"]
    assert "power panel -> G (1 bought), close (Lv G2 A1 R1, SP 350, keep 300)" in capsys.readouterr().out


def test_visit_level_confirmed_tap_keeps_a_lower_later_read(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels["Growth"] = [1, 1, 2]
    visit(p, perc, [1000, 1000, 800], P100)                 # the read is lower than sp0 - price: it wins
    out = capsys.readouterr().out
    assert "power panel: Growth tap not confirmed (SP 800 -> 800)" in out
    assert "power panel -> Gg (1 bought), close (Lv G2 A1 R1, SP 800, keep 300)" in out


def test_visit_unconfirmed_tap_stops_and_strikes(capsys):
    p, g, inj, perc, saver, clock = make()
    p.sleeps.clear()
    visit(p, perc, [1000], P100)                            # SP constant, level digits constant
    out = capsys.readouterr().out
    assert card_taps(inj) == ["Growth"]                     # one tap, then the visit ends
    assert "power panel: Growth tap not confirmed (SP 1000 -> 1000)" in out
    assert "power panel -> g (0 bought), close (Lv G1 A1 R1, SP 1000, keep 300)" in out
    assert p.power.levels()["Growth"] == 1 and p.power.record()["unconfirmed"] == 1
    assert p.sleeps.count(0.5) == sp.CONFIRM_TRIES == 2
    visit(p, perc)                                          # second miss in a row: Growth is maxed
    assert "power card Growth maxed at Lv 1" in capsys.readouterr().out
    assert p.power.available() == ("Alignment", "Resonance")


def test_visit_unconfirmed_tap_with_unreadable_sp_is_no_strike(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [1000, 1000, None], P100)
    assert "power panel: Growth tap not confirmed (SP 1000 -> ?)" in capsys.readouterr().out
    visit(p, perc, [1000, 1000, None])
    assert "maxed" not in capsys.readouterr().out and p.power.available() == tuple(CARDS)


def test_visit_price_unreadable_skips_card_and_goes_on(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [1000, 1000, 900, 800], {"Growth": [None], "Alignment": [100], "Resonance": [100]})
    assert "power panel: Growth price unreadable -- skipped" in capsys.readouterr().out
    assert card_taps(inj)[:2] == ["Alignment", "Alignment"]  # the next card in order; Growth is not tapped
    assert "Growth" not in card_taps(inj)


def test_visit_uses_the_last_confirmed_price_as_fallback(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [450, 450, 400, 300], P100)
    assert p.power.last_price("Growth") == 100
    inj.taps.clear()
    visit(p, perc, [450, 450, 400, 300], {c: [None] for c in CARDS})   # price unreadable now
    assert card_taps(inj) == ["Growth", "Growth"]
    assert "price unreadable" not in capsys.readouterr().out
    assert p.power.levels()["Growth"] == 5


def test_visit_fallback_price_still_respects_the_reserve(capsys):
    p, g, inj, perc, saver, clock = make()
    p.power.confirmed("Growth", 200)
    visit(p, perc, [450, 450], {c: [None] for c in CARDS})  # 450 - 200 < 300
    assert card_taps(inj) == []
    assert "power panel: nothing to buy (SP 450, keep 300) -- closed" in capsys.readouterr().out


def test_visit_all_prices_unreadable_ends_with_nothing_to_buy(capsys):
    p, g, inj, perc, saver, clock = make()
    visit(p, perc, [1000, 1000], {c: [None] for c in CARDS})
    out = capsys.readouterr().out
    for c in CARDS:
        assert f"power panel: {c} price unreadable -- skipped" in out
    assert "power panel: nothing to buy (SP 1000, keep 300) -- closed" in out
    assert card_taps(inj) == []


def test_visit_buy_max_per_visit(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.live = 1_000_000
    visit(p, perc)
    assert len(card_taps(inj)) == sp.BUY_MAX == 10
    assert "(10 bought)" in capsys.readouterr().out


def test_panel_saves_are_capped_per_game():
    p, g, inj, perc, saver, clock = make()
    perc.cards = {c: None for c in CARDS}
    for _ in range(sp.PANEL_SAVE_MAX + 5):
        visit(p, perc)
    paths = [path for _, path in saver.saved if "panel_" in path]
    assert sp.PANEL_SAVE_MAX == 20 and len(paths) == 20


def test_visit_closes_until_closed():
    p, g, inj, perc, saver, clock = make(close_after=3)
    visit(p, perc, [399, 399])
    assert inj.taps.count(UI["power_close"]) == 3


def test_visit_unread_card_is_counted(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7], "Alignment": [None], "Resonance": [1]}
    visit(p, perc, [399, 399])
    assert "Lv check: Growth read 7, count 1 (count kept)" in capsys.readouterr().out


def test_visit_missing_card_does_not_make_src_count():
    p, g, inj, perc, saver, clock = make()
    perc.cards = {"Growth": CARDS["Growth"], "Alignment": None, "Resonance": CARDS["Resonance"]}
    visit(p, perc, list(DROPPING), P100)
    assert p.power.record()["lv_check"]["mismatch"] == 1
    assert CARDS["Alignment"] not in inj.taps
    assert card_taps(inj)[-1] == "Resonance"


def test_visit_two_different_reads_are_unread(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.levels = {"Growth": [7, 8], "Alignment": [1], "Resonance": [1]}
    visit(p, perc, [399, 399])
    assert "Lv check: read G- A1 R1 = count" in capsys.readouterr().out


def test_visit_no_cards_found(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.cards = {"Growth": None, "Alignment": None, "Resonance": None}
    visit(p, perc, [1000])
    assert "power panel: cards not found -- closed" in capsys.readouterr().out
    assert inj.taps == [UI["power_close"]]


def test_visit_prints_maxed_line(capsys, monkeypatch):
    p, g, inj, perc, saver, clock = make()
    real = p.power.start_visit

    def start(read, found=None):
        return real(read, found) + ["power card Growth maxed at Lv 8"]

    monkeypatch.setattr(p.power, "start_visit", start)
    visit(p, perc, [399, 399])
    assert "power card Growth maxed at Lv 8" in capsys.readouterr().out


def test_visit_skips_maxed_card():
    p, g, inj, perc, saver, clock = make()
    p.power._maxed.append("Alignment")
    p.power._bought["Growth"] = 6                           # Growth Lv 7: Alignment would come next
    visit(p, perc, [1000, 1000, 900], P100)
    assert CARDS["Alignment"] not in inj.taps
    assert card_taps(inj)[0] == "Resonance"


def test_trigger_then_visit_through_tick(capsys):
    p, g, inj, perc, saver, clock = armed(sps=1000)
    perc.panel_sps = [1000, 1000, 900, 800]
    perc.prices = dict(P100)
    ticks(p, 2)
    assert opens(inj) == 1
    perc.panel = True
    ticks(p, 1)                                             # BasePlayer routes the open panel to power_visit
    assert card_taps(inj) == ["Growth"] * 3
    assert "power panel -> GGg (2 bought), close (Lv G3 A1 R1, SP 800, keep 300)" in capsys.readouterr().out


# ---- AC4 score and milestones --------------------------------------------------------------

def test_milestones_with_score(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE)
    perc.scores = [1000]
    ticks(p, 3)
    out = capsys.readouterr().out
    assert "milestone m1 reached at score 1000 (Res7 2, Align7 3, Bubble 2)" in out
    assert "milestone m3 reached at score 1000" in out
    paths = [path for _, path in saver.saved]
    for m in ("m1", "m2", "m3"):
        assert f"data/support_runs/G/{m}_1000.png" in paths
    rec = p.milestones.record()
    assert rec["milestones"]["m2"]["shot"] == "data/support_runs/G/m2_1000.png"
    assert rec["scores_confirmed"] >= 1 and rec["max_score"] == 1000


def test_milestone_without_score_is_na(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 3)
    assert "milestone m1 reached at score ? (Res7 2, Align7 3, Bubble 2)" in capsys.readouterr().out
    assert "data/support_runs/G/m1_na.png" in [path for _, path in saver.saved]
    assert p.milestones.record()["milestones"]["m1"]["score"] is None


def test_single_score_read_is_not_confirmed():
    p, g, inj, perc, saver, clock = make(COMPLETE)
    perc.scores = [1000, 3000, 1000, 3000]                  # never two identical reads in a row
    ticks(p, 4)
    assert p.milestones.record()["scores_confirmed"] == 0


def test_crossing_event(capsys):
    p, g, inj, perc, saver, clock = make()
    perc.scores = [2000]
    ticks(p, 2)
    assert "score crossed 2000 (Res7 0, Align7 0, Bubble 0)" in capsys.readouterr().out
    assert "data/support_runs/G/cross_2000_2000.png" in [path for _, path in saver.saved]
    assert p.milestones.record()["crossings"]["2000"]["shot"] == "data/support_runs/G/cross_2000_2000.png"


def test_covered_window_stores_null_shot(capsys):
    p, g, inj, perc, saver, clock = make(COMPLETE, covered=True)
    perc.scores = [2000]
    ticks(p, 3)
    rec = p.milestones.record()
    assert rec["milestones"]["m1"]["shot"] is None
    assert rec["crossings"]["2000"]["shot"] is None
    assert "milestone m1" in capsys.readouterr().out


def test_unconfirmed_board_does_not_feed_milestones():
    p, g, inj, perc, saver, clock = make(COMPLETE)
    ticks(p, 1)                                             # first read only
    assert p.milestones.record()["milestones"]["m1"]["reached"] is False


# ---- AC5 play() ----------------------------------------------------------------------------

class FakeRunPlayer:
    made = []

    def __init__(self, g, inj, saver, game_id=None, tick=0.6, trial=False):
        self.args = (g, inj, saver, game_id, tick, trial)
        self.stats = {"merges": 3, "fails": 1, "support": 2, "complete": True}
        self.last_frame = "LAST"
        FakeRunPlayer.made.append(self)

    def run(self, minutes):
        self.minutes = minutes
        return "game_over"


class FakeCollect(FakeRunPlayer):
    kind = "collect"


class FakePlay(FakeRunPlayer):
    kind = "play"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.milestones = MilestoneTracker()
        self.power = PowerTracker()
        self.power.confirmed("Alignment", 100)
        self.power.start_visit({"Growth": 1, "Alignment": 2, "Resonance": 1})


@pytest.fixture
def run_env(monkeypatch, tmp_path):
    FakeRunPlayer.made = []
    saver = RecSaver()
    monkeypatch.setattr(sb, "Saver", lambda g: saver)
    monkeypatch.setattr(sb, "new_game_id", lambda now=None: "sup_T")
    monkeypatch.setattr(sb, "ROUNDS_FILE", str(tmp_path / "data" / "support_rounds.jsonl"))
    monkeypatch.setattr(sp.Perception, "read_score", lambda self, f: None)   # last_frame is a fake string
    monkeypatch.setattr(sp, "CollectPlayer", FakeCollect)
    monkeypatch.setattr(sp, "PlayPlayer", FakePlay)

    def gates(type_, pip):
        monkeypatch.setattr(sb.support, "gate_state", lambda: {"type": type_, "pip": pip})

    return saver, tmp_path / "data" / "support_rounds.jsonl", gates


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("type_,pip,mode,line", [
    (False, False, "collect", "support deck: collect mode (type gate not passed)"),
    (True, False, "trial", "support deck: trial mode (type gate PASS, pip gate FAIL)"),
    (True, True, "play", "support deck: play mode (type gate PASS, pip gate PASS)"),
])
def test_play_modes(run_env, capsys, type_, pip, mode, line):
    saver, path, gates = run_env
    gates(type_, pip)
    g, inj = FakeGrabber(), FakeInjector()
    res = sb.play(g, inj, minutes=1, tick=0.1)
    assert res == "game_over"
    assert line in capsys.readouterr().out
    pl = FakeRunPlayer.made[0]
    assert type(pl) is (FakeCollect if mode == "collect" else FakePlay)
    assert pl.args[:5] == (g, inj, saver, "sup_T", 0.1)
    assert pl.args[5] == (mode == "trial")
    assert ("LAST", "data/support_runs/sup_T/end.png") in saver.saved
    rec = lines(path)[0]
    assert rec["mode"] == mode and rec["result"] == "game_over"
    assert rec["gates"] == {"type": type_, "pip": pip}
    assert rec["stats"] == {"merges": 3, "fails": 1, "support": 2, "complete": True}
    if mode == "collect":
        assert rec["power"] is None
    else:
        assert rec["power"]["levels"] == {"Growth": 1, "Alignment": 2, "Resonance": 1}
        assert rec["power"]["src"] == "count"
    assert sb.play.stats == {"merges": 3, "fails": 1, "support": 2, "complete": True}


def test_play_forced_mode_skips_the_gate(run_env):
    saver, path, gates = run_env
    gates(False, False)
    sb.play(FakeGrabber(), FakeInjector(), mode="play")
    assert type(FakeRunPlayer.made[0]) is FakePlay and FakeRunPlayer.made[0].args[5] is False
    assert lines(path)[0]["mode"] == "play"


def test_play_appends_one_line_per_game(run_env):
    saver, path, gates = run_env
    gates(True, True)
    sb.play(FakeGrabber(), FakeInjector())
    sb.play(FakeGrabber(), FakeInjector())
    assert len(lines(path)) == 2


# ---- AC6 main() ----------------------------------------------------------------------------

@pytest.mark.parametrize("argv,execute,mode", [
    ([], False, None),
    (["--execute"], True, None),
    (["--mode", "auto"], False, None),
    (["--mode", "collect"], False, "collect"),
    (["--mode", "play", "--execute", "--minutes", "5", "--tick", "0.8"], True, "play"),
])
def test_main_dry_run_default_and_forced_mode(monkeypatch, argv, execute, mode):
    import rdom.input.inject as inject
    made, calls = [], []

    class FakeInj:
        def __init__(self, execute=False):
            made.append(execute)

    class FakeG:
        def close(self):
            calls.append("close")

    monkeypatch.setattr(inject, "Injector", FakeInj)
    monkeypatch.setitem(sys.modules, "rdom.capture.live", types.SimpleNamespace(LiveGrabber=FakeG))
    monkeypatch.setattr(sb, "play", lambda g, inj, minutes, tick, mode=None: calls.append((minutes, tick, mode)))
    monkeypatch.setattr(sys, "argv", ["support_bot.py", *argv])
    sb.main()
    assert made == [execute]
    assert calls[0][2] == mode and calls[-1] == "close"
    if "--minutes" in argv:
        assert calls[0][:2] == (5.0, 0.8)


# ---- AC7 -----------------------------------------------------------------------------------

def test_no_loop_modules_imported():
    for name in ("tools.gear_loop", "tools.run_all", "tools.supervisor", "tools.discord_bot",
                 "gear_loop", "run_all", "supervisor", "discord_bot"):
        assert name not in sys.modules
