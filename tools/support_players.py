"""Support-deck per-tick players: shared skeleton (BasePlayer) and the collect-mode player.

BasePlayer.tick order, first match wins (reference: tools/gear_bot.py play()):
  window moved -> stop; game over -> stop; tactic card -> tap it; hunt popup -> tap its 사냥;
  power panel -> subclass hook; hunt button -> tap (>= 3 s apart); non-battle -> nothing;
  then the data cadence (cells 15 s, full frame 30 s) and the subclass battle_tick.
CollectPlayer only summons, takes one power-panel snapshot and saves training data. It never
touches the board, never taps hpsp/transcend and never buys a power-up.
PlayPlayer plays the board (trial and play mode): confirmed-board guards, merge ban, supporter
cooldown and banner reactions. Importing this module has no side effects.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.input.inject import cell_uv
from rdom.perception import board, collect, gear, score, support
from rdom.policy.milestones import MilestoneTracker
from rdom.policy.power import PowerTracker, load_power_config, plan_visit
from rdom.policy.support import evaluate_support, load_support_deck, plan_support

CELLS_EVERY = 15.0
FRAME_EVERY = 30.0
HUNT_EVERY = 3.0
SUMMON_GAP = 1.0
PANEL_AT = 120.0               # battle seconds before the one power-panel snapshot
PANEL_CLOSE_TRIES = 4
BUFF_STEADY = 4                # identical reads a buffed cell needs (gear_bot)
SUPPORT_CD = 130.0
PLAY_SUMMON_GAP = 0.5
OCR_EVERY = 3.0
CLONE_FOR = 45.0
POWER_HOLD_FOR = 65.0
BAN_FOR = 90.0
MAX_JUNK = 3
POWER_EVERY = 20.0
BUY_GAP = 0.15
LEVEL_REREAD = 0.3


class Perception:
    """Thin wrappers over the rdom recognisers so tests can script what a tick sees."""

    def is_battle(self, f):
        return board.is_battle(f)

    def is_game_over(self, f):
        return board.is_game_over(f)

    def board_glare(self, f):
        return board.board_glare(f)

    def ui_state(self, f):
        return gear.ui_state(f)

    def power_buttons(self, f):
        return gear.power_buttons(f)

    def tactic_sp1000_card(self, f):
        return gear.tactic_sp1000_card(f)

    def banner_present(self, f):
        return gear.banner_present(f)

    def banner_text(self, f):
        return gear.banner_text(f)

    def effect_kind(self, text):
        return gear.effect_kind(text)

    def buffed_cells(self, f):
        return gear.buffed_cells(f)

    def cell_crops(self, f):
        return gear.cell_crops(f)

    def read_board_support(self, f, pip_source="auto"):
        return support.read_board_support(f, pip_source)

    def power_cards(self, f):
        return support.power_cards(f)

    def card_level(self, f, button):
        return support.card_level(f, button)

    def read_score(self, f):
        return score.read_score(f)


class BasePlayer:
    def __init__(self, g, inj, saver, perc=None, game_id=None, clock=time.monotonic,
                 sleep=time.sleep, tick=0.6):
        self.g, self.inj, self.saver = g, inj, saver
        self.perc = perc or Perception()
        if game_id is None:
            from support_bot import new_game_id
            game_id = new_game_id()
        self.game_id = game_id
        self.clock, self.sleep, self.tick_s = clock, sleep, tick
        self.stats = {"merges": 0, "fails": 0, "support": 0, "complete": False}
        self.battle_start = None
        self.last_frame = None                 # last battle frame, saved as end.png by play()
        self._hunt_last = -1e9
        self._cells_last = -1e9
        self._frame_last = -1e9

    def tap(self, key):
        self.inj.tap(*gear.UI[key])

    def t(self, now):
        """Seconds since the first battle frame (0.0 before it)."""
        return 0.0 if self.battle_start is None else now - self.battle_start

    # hooks
    def on_panel(self, f, ui, now):
        raise NotImplementedError

    def battle_tick(self, f, ui, now):
        raise NotImplementedError

    def close_panel(self):
        for _ in range(PANEL_CLOSE_TRIES):                 # make sure it really closes
            self.tap("power_close")
            self.sleep(0.6)
            if not self.perc.ui_state(self.g.grab())["power_panel"]:
                break

    def tick(self):
        """One loop step. Returns "moved" / "game_over" to stop, else None."""
        try:
            if self.g.window_moved():
                print("window moved -- stopping")
                return "moved"
        except OSError:
            return None
        f = self.g.grab()
        now = self.clock()
        perc = self.perc
        if perc.is_game_over(f):
            print("game over")
            return "game_over"
        card = perc.tactic_sp1000_card(f)
        if card:
            print(f"tactic screen -> 즉시 SP1000 at v={card[1]}", flush=True)
            self.inj.tap(*card)
            self.sleep(1.2)
            return None
        ui = perc.ui_state(f)
        if ui["hunt_popup"]:
            print("hunt popup -> 사냥")
            self.tap("hunt_popup_ok")
            return None
        if ui["power_panel"]:
            self.on_panel(f, ui, now)
            return None
        if ui["hunt"] and now - self._hunt_last >= HUNT_EVERY:
            print("hunt")
            self.tap("hunt")
            self._hunt_last = now
            return None
        if not perc.is_battle(f):
            return None                                    # menu / banner over the summon button
        if self.battle_start is None:
            self.battle_start = now
        self.last_frame = f
        t = self.t(now)
        if t - self._cells_last >= CELLS_EVERY:
            self._cells_last = t
            # AI-NOTE: the Saver re-checks unobscured on every call (R6); the player never writes itself.
            self.saver.cells(f, self.game_id, t, buffed=perc.buffed_cells(f),
                             glare=perc.board_glare(f))
        if t - self._frame_last >= FRAME_EVERY:
            self._frame_last = t
            self.saver.frame(f, f"data/support_frames/{self.game_id}/{t:.1f}.png")
        self.battle_tick(f, ui, now)
        return None

    def run(self, minutes=30):
        """Play until game over / window move / timeout. Returns "game_over", "moved" or "timeout"."""
        t_end = self.clock() + minutes * 60
        while self.clock() < t_end:
            self.sleep(self.tick_s)
            res = self.tick()
            if res:
                return res
        return "timeout"


class CollectPlayer(BasePlayer):
    """Collect mode: summon, one power-panel snapshot, save data. No board action, no purchase."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._summon_last = -1e9
        self._opened = False
        self._snapped = False

    def on_panel(self, f, ui, now):
        if self._opened and not self._snapped:
            self._snapped = True
            t = self.t(now)
            self.saver.frame(f, f"data/support_frames/{self.game_id}/panel_{t:.1f}.png")
        # AI-NOTE: closing only -- the cards are never tapped, so collect mode cannot buy a power-up.
        self.close_panel()

    def battle_tick(self, f, ui, now):
        if not self._opened and self.t(now) >= PANEL_AT:
            self._opened = True
            self.tap("power_open")
            return
        if now - self._summon_last >= SUMMON_GAP:
            self.tap("summon")
            self._summon_last = now


def fmt_board(b):
    """15 tokens <Ty><pip> (first two letters of the type), '...' for an empty cell."""
    return " ".join("..." if d["type"] == "empty" else f"{d['type'][:2]}{d['pip']}" for d in b)


class PlayPlayer(BasePlayer):
    """Board play for trial and play mode (spec R13 steps 8, 9, 11). trial=True reads pips with the
    gear model only. Also the power bar (step 10), the power visit (R20) and score/milestone
    tracking (R14)."""

    def __init__(self, *a, trial=False, deck=None, power_cfg=None, **kw):
        super().__init__(*a, **kw)
        self.trial = trial
        self.deck = deck or load_support_deck(gear.DECK_FILE)
        self.pip_source = "gear" if trial else "auto"
        self._summon_last = -1e9
        self._support_last = -1e9
        self._ocr_last = -1e9
        self._covered_logged = -1e9
        self.clone_until = -1e9
        self.hold_power_until = -1e9           # no power-up before this time (sp_double_later banner)
        self._power_last = -1e9
        self.power_cfg = power_cfg or load_power_config(gear.DECK_FILE)
        self.power = PowerTracker()
        self.score_tracker = score.ScoreTracker()
        self.milestones = MilestoneTracker()
        self.bonus_until = -1e9
        self._prev_sig = None
        self._hist = {}                        # cell -> last BUFF_STEADY reads
        self._banned = {}                      # (from, to) -> (from type, to type, expiry)
        self._pending = None                   # (from, to, board) of the last merge swipe

    def on_panel(self, f, ui, now):
        self.power_visit(f)

    def power_visit(self, f):
        """R20 steps 1-8 on the open power panel frame f."""
        perc, tracker = self.perc, self.power
        now = self.clock()
        self._power_last = now
        self.saver.frame(f, f"data/support_frames/{self.game_id}/panel_{self.t(now):.1f}.png")
        found = {c: uv for c, uv in perc.power_cards(f).items() if uv}
        if not found:
            print("power panel: cards not found -- closed", flush=True)
            self.close_panel()
            return
        # AI-NOTE: levels are read only here, twice 0.3 s apart, never after a buy tap -- the number
        # updates a beat after the tap (HP reader lesson); a level counts only if both reads agree.
        first = {c: perc.card_level(f, uv) for c, uv in found.items()}
        self.sleep(LEVEL_REREAD)
        f2 = self.g.grab()
        read = {}
        for c, uv in found.items():
            lv = perc.card_level(f2, uv)
            read[c] = lv if lv is not None and lv == first[c] else None
        levels, src, lines = tracker.start_visit(read, set(found))
        for line in lines:
            print(line, flush=True)
        avail = [c for c in tracker.available() if c in found]
        seq = plan_visit(levels, avail, self.power_cfg, 6)
        if not seq:
            print("power panel: nothing to buy -- closed", flush=True)
            self.close_panel()
            return
        for c in seq:
            self.inj.tap(*found[c])
            self.sleep(BUY_GAP)
        tracker.tapped(seq)
        print(PowerTracker.line(seq, levels, src), flush=True)
        self.close_panel()
        self._power_last = self.clock()

    def _events(self, f, events):
        """Print each milestone/crossing log line and save its screenshot (R14, R6)."""
        for ev in events:
            print(ev["log"], flush=True)
            if ev["kind"] == "milestone":
                name = f"{ev['name']}_{'na' if ev['score'] is None else ev['score']}.png"
            else:
                name = f"cross_{ev['limit']}_{ev['score']}.png"
            # AI-NOTE: the Saver returns None for a covered window, so the shot is stored as null.
            path = self.saver.frame(f, f"data/support_runs/{self.game_id}/{name}")
            self.milestones.set_shot(ev, path)

    def _power_due(self, now):
        return now - self._power_last >= POWER_EVERY and now > self.hold_power_until

    def _banner(self, f, now):
        if now - self._ocr_last <= OCR_EVERY or not self.perc.banner_present(f):
            return
        self._ocr_last = now
        kind = self.perc.effect_kind(self.perc.banner_text(f))
        if kind == "destroy3_clone_max" and now > self.clone_until:
            print("EFFECT: destroy 3 lowest + clone max in ~40s -> keep a gear on top")
            self.clone_until = now + CLONE_FOR
        elif kind == "sp_double_later" and now > self.hold_power_until:
            print("EFFECT: SP doubles in 60s -> holding power-ups")
            self.hold_power_until = now + POWER_HOLD_FOR
        elif kind == "summon_bonus_when_short" and now > self.bonus_until:
            # AI-NOTE: not acted on -- tapping summon on a full field broke merges in the gear bot.
            print("EFFECT: summon bonus when short (no action)")
            self.bonus_until = now + 60

    def _save_fail(self, f, a, b, now):
        # AI-NOTE: R5/R6 -- collect.save_fail writes crops itself, so check the window here.
        if self.g.unobscured():
            collect.save_fail(f, a, b)
        elif now - self._covered_logged >= 60.0:
            print("frame not saved: game window covered")
            self._covered_logged = now

    def battle_tick(self, f, ui, now):
        self._banner(f, now)
        confirmed = self.score_tracker.update(self.perc.read_score(f))
        if confirmed is not None:
            self._events(f, self.milestones.on_score(confirmed))
        b = self.perc.read_board_support(f, pip_source=self.pip_source)
        sig = tuple((d["type"], d["pip"]) for d in b)
        stable = sig == self._prev_sig
        self._prev_sig = sig
        for d in b:
            h = self._hist.setdefault(d["cell"], [])
            h.append((d["type"], d["pip"]))
            del h[:-BUFF_STEADY]
        buffed = self.perc.buffed_cells(f)
        bc = {d["cell"]: d for d in b}
        if self._pending:                      # verify the last merge took effect
            fr, to, before = self._pending
            self._pending = None
            if all(bc[c]["type"] == before[c]["type"] and bc[c]["pip"] == before[c]["pip"]
                   for c in (fr, to)):
                # AI-NOTE: ban keyed on type only, as in gear_bot -- a flickering pip read must not clear it.
                self._banned[(fr, to)] = (bc[fr]["type"], bc[to]["type"], now + BAN_FOR)
                print(f"   merge {fr}->{to} had no effect -> banned until those dice change")
                self._save_fail(f, bc[fr], bc[to], now)
                self.stats["fails"] += 1
        self._banned = {k: v for k, v in self._banned.items()
                        if v[:2] == (bc[k[0]]["type"], bc[k[1]]["type"]) and now < v[2]}

        ev = evaluate_support(b, self.deck)
        if ev["complete"]:
            self.stats["complete"] = True
        if not stable and not ev["empty"]:
            return                             # wait for a confirming read
        if ev["unknown"] > MAX_JUNK:
            return                             # popup/banner covering the board
        if stable:
            self._events(f, self.milestones.on_board(
                {"res7": ev["res7"], "align7": ev["align7"], "bubbles": ev["bubbles"]}))
        if ev["complete"] and self._power_due(now):
            print("power-up (complete)", flush=True)
            self.tap("power_open")
            self._power_last = now
            return
        act = plan_support(b, self.deck, support_ready=now - self._support_last >= SUPPORT_CD,
                           banned=set(self._banned), clone_alert=now < self.clone_until)
        op = act["op"]
        if op in ("merge", "support"):
            cells = [c for c in (act.get("from"), act.get("to")) if c in buffed]
            if any(len(self._hist[c]) < BUFF_STEADY or len(set(self._hist[c])) > 1 for c in cells):
                return                         # buffed cell not steady yet
        if op == "summon":
            if now - self._summon_last >= PLAY_SUMMON_GAP:
                self.tap("summon")
                self._summon_last = now
        elif op == "merge":
            print(f"{fmt_board(b)} | R7 {ev['res7']} L7 {ev['align7']} B{ev['bubbles']} "
                  f"-> merge {act['from']}->{act['to']}", flush=True)
            self.inj.swipe(*cell_uv(act["from"]), *cell_uv(act["to"]))
            self._pending = (act["from"], act["to"], bc)
            self.stats["merges"] += 1
        elif op == "support":
            print(f"{fmt_board(b)} -> supporter <- {act['from']}", flush=True)
            self.inj.swipe(*cell_uv(act["from"]), *gear.UI["support"], dur_ms=400)
            self._support_last = now
            self.stats["support"] += 1
        elif op == "wait" and self._power_due(now):
            # nothing to do on the board -> spend SP (gear_bot wording)
            print(f"idle ({act.get('why')}) -> power-up", flush=True)
            self.tap("power_open")
            self._power_last = now
