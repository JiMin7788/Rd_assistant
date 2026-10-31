"""Support-deck per-tick players: shared skeleton (BasePlayer) and the collect-mode player.

BasePlayer.tick order, first match wins (reference: tools/gear_bot.py play()):
  window moved -> stop; game over -> stop; dice info panel -> tap 소환 to close; tactic card -> tap it; hunt popup -> tap its 사냥;
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

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.input.inject import cell_uv
from rdom.perception import board, collect, gear, score, support
from rdom.perception import sp as spread
from rdom.perception.support_memory import CellMemory, _unreadable, burst_result, merge_verdict
from rdom.policy.milestones import MilestoneTracker
from rdom.policy.power import PowerTracker, keep as power_keep, load_power_config, next_card
from rdom.policy.support import evaluate_support, load_support_deck, plan_support

CELLS_EVERY = 15.0
FRAME_EVERY = 30.0
HUNT_EVERY = 3.0
INFO_TAP_GAP = 1.0             # min seconds between two 소환 taps that close the dice info panel
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
VERIFY_TICKS = 3               # undecided merge verifications before it counts as an effect
POWER_EVERY = 20.0
BUY_MAX = 10                   # buy taps per panel visit (one card at a time, each confirmed)
PANEL_SAVE_MAX = 20            # saved power-panel frames per game
PRICE_NONE_SAVE_MAX = 10       # saved panel frames per game on which a price was unreadable (real 4-digit crops for H3)
CONFIRM_TRIES = 2              # grabs after a buy tap that look for the confirmation
CONFIRM_WAIT = 0.5
LEVEL_REREAD = 0.3
PANEL_SP_RETRY_WAIT = 0.25     # between extra panel grabs while the SP digits are covered by a popup
PANEL_SP_RETRY_FOR = 1.0       # give up on the panel SP read after this many seconds
BURST_N = 6                    # tick frame + 5 grabs
BURST_DT = 0.08
BURST_GAP = 3.0                # min seconds between two bursts
BURST_REFRESH = 15.0           # remembered cells (and cells with BURST_FAILS failures) re-burst this late
BURST_FAILS = 3
BURST_SAVE_GAP = 10.0
BURST_SAVE_MAX = 60
GAME_OVER_TICKS = 2            # consecutive result-screen ticks (game-over look, battle UI gone) before stopping
LOOKALIKE_LOG_EVERY = 10.0     # min seconds between two 'look-alike ignored' lines
GAME_OVER_SHOTS_MAX = 3        # saved look-alike / seen-once frames per game, each kind


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

    def dice_info_panel(self, f):
        return gear.dice_info_panel(f)

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

    def read_sp(self, f):
        return spread.read_sp(f)

    def read_summon_cost(self, f):
        return spread.read_summon_cost(f)

    def read_panel_sp(self, f):
        return spread.read_panel_sp(f)

    def read_price(self, f, button_uv):
        return spread.read_price(f, button_uv)

    def read_cells_support(self, f, cells, pip_source="auto"):
        return support.read_cells_support(f, cells, pip_source)

    def frames_equal(self, a, b):
        return np.shape(a) == np.shape(b) and bool(np.array_equal(a, b))


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
        self._info_last = -1e9                 # last 소환 tap that closed the dice info panel
        self._go_ticks = 0                     # consecutive result-screen ticks so far
        self._look_last = -1e9                 # last 'look-alike ignored' line
        self._look_saved = 0
        self._once_saved = 0
        self._go_seen = None                   # frame of the last pending result-like tick

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

    def _save_go(self, f, now, name):
        """Save a game-over diagnostic frame through the Saver; True when it was written."""
        path = f"data/support_runs/{self.game_id}/{name}_{self.t(now):.1f}.png"
        return self.saver.frame(f, path) is not None

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
        # AI-NOTE: the game-over colour test also fires on battle frames (H2 06:39 stopped a running game
        # after 31 s). Stop only when the battle UI is gone too, on GAME_OVER_TICKS ticks in a row.
        over = perc.is_game_over(f)
        if over and not perc.is_battle(f):
            self._go_ticks += 1
            if self._go_ticks >= GAME_OVER_TICKS:
                print("game over")
                return "game_over"
            self._go_seen = f
            return None                                    # pending: no board action on this tick
        if self._go_ticks:
            self._go_ticks = 0
            print("game-over screen seen once -- not confirmed", flush=True)
            # AI-NOTE: save the frame the result-like screen was seen on, not this (battle) frame.
            if self._once_saved < GAME_OVER_SHOTS_MAX and self._save_go(self._go_seen, now, "gameover_once"):
                self._once_saved += 1
        if over and now - self._look_last >= LOOKALIKE_LOG_EVERY:
            self._look_last = now
            print("game-over look-alike ignored (battle screen visible)", flush=True)
            if self._look_saved < GAME_OVER_SHOTS_MAX and self._save_go(f, now, "gameover_lookalike"):
                self._look_saved += 1
        # AI-NOTE: before the tactic check -- the info panel under a boss banner is dark at the three tactic
        # card rows, so the tactic OCR would tap a card position on it. Only the first 소환 tap closes the
        # panel (no summon, no SP spent); the gap keeps a tap storm from summoning once it is closed.
        if perc.dice_info_panel(f):
            if now - self._info_last >= INFO_TAP_GAP:
                print("dice info panel -> 소환 (close)", flush=True)
                self.tap("summon")
                self._info_last = now
            return None                                    # no board read, memory, burst or crop for this frame
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
    return " ".join("..." if d["type"] == "empty"
                    else f"{d['type'][:2]}{d['pip']}" + ("*" if d.get("src") in ("memory", "burst") else "")
                    for d in b)


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
        self.cost = None                       # summon cost read identically on 2 consecutive ticks
        self._cost_last = None
        self._sp_prev = None
        self._panel_saves = 0
        self._price_saves = 0
        self.score_tracker = score.ScoreTracker()
        self.milestones = MilestoneTracker()
        self.bonus_until = -1e9
        self._prev_sig = None
        self._hist = {}                        # cell -> last BUFF_STEADY reads
        self._banned = {}                      # (from, to) -> (from type, to type, expiry)
        self._pending = None                   # [from, to, {cell: (type, pip)} at the swipe, undecided ticks]
        self.memory = CellMemory(support.READ_CONF_MIN, empty_conf_min=support.EMPTY_CONF_MIN)
        self.burster = Burster(self)
        self._unk_logged = set()               # cells whose 'occupied, unknown' line was printed
        self.stats.update(bursts=0, burst_hits=0, mem_ticks=0, forgets=0)

    def on_panel(self, f, ui, now):
        self.power_visit(f)

    def power_visit(self, f):
        """R7 on the open power panel frame f: one confirmed purchase at a time above the reserve."""
        perc, tracker = self.perc, self.power
        now = self.clock()
        self._power_last = now
        self._sp_prev = None                   # the SP read before the panel is stale after a visit
        if self._panel_saves < PANEL_SAVE_MAX:
            self._panel_saves += 1
            self.saver.frame(f, f"data/support_frames/{self.game_id}/panel_{self.t(now):.1f}.png")
        found = {c: uv for c, uv in perc.power_cards(f).items() if uv}
        if not found:
            print("power panel: cards not found -- closed", flush=True)
            self.close_panel()
            return
        # AI-NOTE: the count is cross-checked only with levels read here, twice 0.3 s apart (a level
        # counts if both reads agree); the number updates a beat after a tap (HP reader lesson).
        first = {c: perc.card_level(f, uv) for c, uv in found.items()}
        self.sleep(LEVEL_REREAD)
        f2 = self.g.grab()
        read = {}
        for c, uv in found.items():
            lv = perc.card_level(f2, uv)
            read[c] = lv if lv is not None and lv == first[c] else None
        for line in tracker.start_visit(read, set(found)):
            print(line, flush=True)
        # AI-NOTE: a cyan '+30' popup covers the SP digits on most panel frames (2 of 6 readable), so
        # reads are collected over up to PANEL_SP_RETRY_FOR s until two agree on being numbers; sp0 is
        # the lower of two, as before. Without it most visits closed with 'SP unreadable'.
        reads = [r for r in (perc.read_panel_sp(f), perc.read_panel_sp(f2)) if r is not None]
        waited = 0.0
        while len(reads) < 2 and waited < PANEL_SP_RETRY_FOR:
            self.sleep(PANEL_SP_RETRY_WAIT)
            waited += PANEL_SP_RETRY_WAIT
            f2 = self.g.grab()
            r = perc.read_panel_sp(f2)
            if r is not None:
                reads.append(r)
        sp0 = min(reads) if len(reads) >= 2 else None
        keep = None if self.cost is None else power_keep(self.cost, self.power_cfg)
        # AI-NOTE: an unreadable SP is checked before the unknown keep so it always gives the R7 'SP unreadable' line.
        if sp0 is None:
            print("power panel: SP unreadable -- closed", flush=True)
            self.close_panel()
            return
        if keep is None:
            print(f"power panel: nothing to buy (SP {sp0}, keep ?) -- closed", flush=True)
            self.close_panel()
            return
        base = dict(read)                      # last level read per card, to see a rise after a tap
        skipped, taps, bought, cur, ntaps = set(), "", 0, f2, 0
        while ntaps < BUY_MAX:
            avail = [c for c in tracker.available() if c in found and c not in skipped]
            c = next_card(tracker.levels(), avail, self.power_cfg)
            if c is None:
                break
            # AI-NOTE: never buy on a guessed price (QA round 5: a 1000 price read as None, the stale last price 750 let the
            # bot buy from SP 2240 down to 1240 < keep 1440); tracker.last_price only serves the R6 trigger estimate.
            price = perc.read_price(cur, found[c])
            if not price:
                print(f"power panel: {c} price unreadable -- skipped", flush=True)
                skipped.add(c)
                if self._price_saves < PRICE_NONE_SAVE_MAX:
                    self._price_saves += 1
                    self.saver.frame(cur, f"data/support_runs/{self.game_id}/panel_price_none_{self.t(now):.1f}.png")
                continue
            if sp0 - price < keep:
                break
            self.inj.tap(*found[c])
            ntaps += 1
            ok, sp1 = False, None
            for _ in range(CONFIRM_TRIES):
                self.sleep(CONFIRM_WAIT)
                cur = self.g.grab()
                sp1 = perc.read_panel_sp(cur)
                lv = perc.card_level(cur, found[c])
                # AI-NOTE: this read only confirms the tap; it never sets the count (tracker.levels()).
                rose = lv is not None and base.get(c) is not None and lv > base[c]
                if lv is not None:
                    base[c] = lv if base.get(c) is None else max(base[c], lv)
                if rose or (sp1 is not None and sp1 <= sp0 - price / 2):
                    ok = True
                    break
            if ok:
                tracker.confirmed(c, price)
                taps += c[0]
                bought += 1
                # AI-NOTE: a tap confirmed by the level alone can still show the old SP (the number lags);
                # do not carry that stale value forward -- the spend is known. A read that shows the drop wins.
                dropped = sp1 is not None and sp1 <= sp0 - price / 2
                sp0 = sp1 if dropped else sp0 - price
                continue
            taps += c[0].lower()
            print(f"power panel: {c} tap not confirmed (SP {sp0} -> {'?' if sp1 is None else sp1})", flush=True)
            for line in tracker.not_confirmed(c, affordable=True, sp_known=sp1 is not None):
                print(line, flush=True)
            break
        if not taps:
            print(f"power panel: nothing to buy (SP {sp0}, keep {keep}) -- closed", flush=True)
        else:
            print(PowerTracker.line(taps, tracker.levels(), sp0, keep, bought), flush=True)
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

    def _sp_due(self, now, sp_now, sp_prev):
        """R6: SP of this and the previous tick both cover keep + the next card's last price."""
        if self.cost is None or sp_now is None or sp_prev is None:
            return False
        if now - self._power_last < POWER_EVERY or now <= self.hold_power_until:
            return False
        card = next_card(self.power.levels(), self.power.available(), self.power_cfg)
        if card is None:
            return False
        need = power_keep(self.cost, self.power_cfg) + (self.power.last_price(card) or 0)
        return min(sp_now, sp_prev) >= need

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

    def _log_events(self, events):
        """Print the cell-memory events in the spec R10 wording."""
        for e in events:
            if e["kind"] == "remembered":
                print(f"cell {e['cell']} unreadable -> keep {e['tok']} (last confident read)", flush=True)
            elif e["kind"] == "unknown":
                self._log_unknown(e["cell"])
            elif e["kind"] == "external":
                self.stats["forgets"] += 1
                forgot = ",".join(str(c) for c in e["forgot"]) or "none"
                print(f"board changed without our action at {','.join(str(c) for c in e['cells'])}"
                      f" -> forget remembered {forgot}", flush=True)

    def _log_unknown(self, c):
        if c not in self._unk_logged:
            self._unk_logged.add(c)
            print(f"cell {c} unreadable -> occupied, unknown", flush=True)

    def _burst(self, f, now, eff, unread, cells):
        """Run one burst of `cells` (R8): accepted values go into memory and `eff`; log and save it."""
        mem, conf_min = self.memory, support.READ_CONF_MIN
        before = {c: mem.memory(c) for c in cells}
        kept, reads, grabs = self.burster.run(f, cells, self.pip_source)
        ecm = support.EMPTY_CONF_MIN
        results = {c: burst_result(reads[c], conf_min, empty_conf_min=ecm) for c in cells}
        self.burster.done(now, cells, results, reads, conf_min, ecm)
        self.stats["bursts"] += 1
        toks = []
        for c in cells:
            v = results[c]
            toks.append(f"{c}=" + ("?" if v is None else "..." if v[0] == "empty" else f"{v[0][:2]}{v[1]}"))
        # AI-NOTE: the tick frame counts as a grab in the log (6 of 6), the record's `grabs` is grabs taken.
        print(f"burst cells {','.join(str(c) for c in cells)} -> {' '.join(toks)} "
              f"({len(kept)} of {grabs + 1} grabs)", flush=True)
        for c in cells:
            if results[c] is None:
                continue
            self.stats["burst_hits"] += 1
            e, events = mem.apply_burst(c, results[c], unread)
            eff[c - 1] = e
            for ev in events:
                if ev["kind"] == "external":
                    # AI-NOTE: R7.4 dropped these memories (maybe resolved earlier in this burst); the board must not keep the old die.
                    for x in ev["forgot"]:
                        eff[x - 1].update(type="junk", variant="junk", pip=0, src="unknown")
            self._log_events(events)
        for c in cells:
            if results[c] is None and mem.state(c) == "unknown":
                self._log_unknown(c)
        buffed = self.perc.buffed_cells(f)
        t = self.t(now)
        rec = Burster.record(self.game_id, t, cells, grabs, kept, reads, results, before,
                             [c for c in cells if c in buffed], self.perc.board_glare(f))
        self.burster.maybe_save(self.game_id, t, cells, kept, rec)

    def _verify_merge(self, f, raw_by, bc, now):
        """R7.1: judge the last merge on RAW reads against the effective values at the swipe."""
        fr, to, before, tries = self._pending
        verdict = merge_verdict(raw_by[fr], raw_by[to], before[fr], before[to], support.READ_CONF_MIN,
                              support.EMPTY_CONF_MIN)
        if verdict == "undecided":
            tries += 1
            if tries < VERIFY_TICKS:
                self._pending[3] = tries
                return
            # AI-NOTE: cells stayed unreadable for VERIFY_TICKS ticks; assume it worked (no ban, no fail count).
            verdict = "effect"
        self._pending = None
        if verdict == "effect":
            self.memory.merged(fr, to)
            for c in (fr, to):
                if bc[c].get("src") == "memory":
                    # AI-NOTE: the memory was just dropped; this tick's effective board must not keep the stale die.
                    bc[c].update(type="junk", variant="junk", pip=0, src="unknown")
            return
        # AI-NOTE: ban keyed on type only, as in gear_bot -- a flickering pip read must not clear it.
        self._banned[(fr, to)] = (bc[fr]["type"], bc[to]["type"], now + BAN_FOR)
        print(f"   merge {fr}->{to} had no effect -> banned until those dice change")
        self._save_fail(f, bc[fr], bc[to], now)
        self.stats["fails"] += 1

    def battle_tick(self, f, ui, now):
        self._banner(f, now)
        confirmed = self.score_tracker.update(self.perc.read_score(f))
        if confirmed is not None:
            self._events(f, self.milestones.on_score(confirmed))
        sp_now = self.perc.read_sp(f)
        cost = self.perc.read_summon_cost(f)
        if cost is not None and cost == self._cost_last:
            self.cost = cost
        self._cost_last = cost
        sp_prev, self._sp_prev = self._sp_prev, sp_now
        raw = self.perc.read_board_support(f, pip_source=self.pip_source)
        raw_by = {d["cell"]: d for d in raw}
        b, mevents = self.memory.update(raw)
        self._log_events(mevents)
        unread = [d["cell"] for d in raw if self.memory.unreadable(d)]
        due = self.burster.due(now, unread, self.memory)
        if due:
            self._burst(f, now, b, unread, due)
        for c in list(self._unk_logged):
            if self.memory.state(c) != "unknown":
                self._unk_logged.discard(c)
        if any(d.get("src") == "memory" for d in b):
            self.stats["mem_ticks"] += 1
        bc = {d["cell"]: d for d in b}
        if self._pending:                      # verify the last merge took effect (on raw reads)
            self._verify_merge(f, raw_by, bc, now)
        sig = tuple((d["type"], d["pip"]) for d in b)
        stable = sig == self._prev_sig
        self._prev_sig = sig
        for d in b:
            h = self._hist.setdefault(d["cell"], [])
            h.append((d["type"], d["pip"]))
            del h[:-BUFF_STEADY]
        buffed = self.perc.buffed_cells(f)
        self._banned = {k: v for k, v in self._banned.items()
                        if v[:2] == (bc[k[0]]["type"], bc[k[1]]["type"]) and now < v[2]}

        ev = evaluate_support(b, self.deck)
        if ev["complete"]:
            self.stats["complete"] = True
        # AI-NOTE: the SP trigger needs no stable board; its two-read rule is the SP of this and the
        # previous tick (R2). The junk guard and a pending merge still block it.
        if len(unread) <= MAX_JUNK and not self._pending and self._sp_due(now, sp_now, sp_prev):
            print(f"power-up (SP {sp_now} > keep {power_keep(self.cost, self.power_cfg)})", flush=True)
            self.tap("power_open")
            self._power_last = now
            return
        if not stable and not ev["empty"]:
            return                             # wait for a confirming read
        if len(unread) > MAX_JUNK:
            return                             # popup/banner covering the board (raw unreadable cells)
        if stable:
            self._events(f, self.milestones.on_board(
                {"res7": ev["res7"], "align7": ev["align7"], "bubbles": ev["bubbles"]}))
        act = plan_support(b, self.deck, support_ready=now - self._support_last >= SUPPORT_CD,
                           banned=set(self._banned), clone_alert=now < self.clone_until)
        op = act["op"]
        if op in ("merge", "support") and self._pending:
            return                             # a merge is still being verified; summon stays allowed
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
            self._pending = [act["from"], act["to"],
                             {c: (bc[c]["type"], bc[c]["pip"]) for c in (act["from"], act["to"])}, 0]
            self.memory.own_action([act["from"], act["to"]])
            self.stats["merges"] += 1
        elif op == "support":
            print(f"{fmt_board(b)} -> supporter <- {act['from']}", flush=True)
            self.inj.swipe(*cell_uv(act["from"]), *gear.UI["support"], dur_ms=400)
            self._support_last = now
            self.memory.supported(act["from"])
            self.stats["support"] += 1


class Burster:
    """Burst mechanics (spec R8, R9): a few quick grabs + reads of hacked cells. Only grabs and reads;
    it never touches the injector."""

    def __init__(self, player):
        self.p = player
        self.last_any = -1e9
        self.last_burst = {}                   # cell -> time of its last burst (absent = never)
        self.fails = {}                        # cell -> consecutive bursts without an accepted value
        self.saved = 0
        self.last_save = -1e9

    def due(self, now, unreadable_cells, memory):
        """Cells to burst now, ascending: unknown cells plus remembered cells last burst >= BURST_REFRESH ago."""
        if now - self.last_any < BURST_GAP or not 1 <= len(unreadable_cells) <= MAX_JUNK:
            return []
        out = []
        for c in sorted(unreadable_cells):
            age = now - self.last_burst.get(c, -1e9)
            st = memory.state(c)
            if st == "unknown":
                # AI-NOTE: R8 backoff -- a cell that failed BURST_FAILS bursts in a row waits like a remembered one
                if self.fails.get(c, 0) < BURST_FAILS or age >= BURST_REFRESH:
                    out.append(c)
            elif st == "remembered" and age >= BURST_REFRESH:
                out.append(c)
        return out

    def done(self, now, cells, results, reads, conf_min, empty_conf_min=0.0):
        """Book a finished burst. results {cell: accepted (type, pip) | None}, reads {cell: [raw read, ...]}."""
        self.last_any = now
        for c in cells:
            self.last_burst[c] = now
            # AI-NOTE: same predicate as CellMemory, so a NaN conf is not a confident read and does not reset the backoff
            confident = any(not _unreadable(d, conf_min, empty_conf_min) for d in reads.get(c, []))
            self.fails[c] = 0 if results.get(c) is not None or confident else self.fails.get(c, 0) + 1

    def run(self, f, cells, pip_source="auto"):
        """-> (kept frames, {cell: [read per kept frame]}, grabs taken). `f` is the tick frame, kept as is."""
        p = self.p
        kept, grabs = [f], 0
        for _ in range(BURST_N - 1):
            p.sleep(BURST_DT)
            g = p.g.grab()
            grabs += 1
            # AI-NOTE: the grabber repeats the last frame when dxcam sees no change; a repeat must not count as a second read
            if not p.perc.is_battle(g) or p.perc.frames_equal(g, kept[-1]):
                continue
            kept.append(g)
        reads = {c: [] for c in cells}
        for fr in kept:
            for d in p.perc.read_cells_support(fr, cells, pip_source):
                if d["cell"] in reads:
                    reads[d["cell"]].append(d)
        return kept, reads, grabs

    @staticmethod
    def record(game, t, cells, grabs, kept, reads, result, memory, buffed, glare):
        """The bursts.jsonl record (R9). result/memory: {cell: (type, pip) | None}."""
        def val(v):
            return None if v is None else [v[0], v[1]]
        return {"game": game, "t": round(t, 1), "cells": list(cells), "grabs": grabs, "kept": len(kept),
                "reads": {str(c): [[d["type"], d["pip"], round(d["conf"], 3)] for d in rs]
                          for c, rs in reads.items()},
                "result": {str(c): val(v) for c, v in result.items()},
                "memory": {str(c): val(v) for c, v in memory.items()},
                "buffed": sorted(buffed), "glare": bool(glare)}

    def maybe_save(self, game_id, t, cells, kept, record):
        """Save at most every BURST_SAVE_GAP s and BURST_SAVE_MAX times; a covered save (None) does not count."""
        now = self.p.clock()
        if self.saved >= BURST_SAVE_MAX or now - self.last_save < BURST_SAVE_GAP:
            return None
        names = self.p.saver.burst(game_id, t, cells, kept, record)
        if names is None:
            return None
        self.saved += 1
        self.last_save = now
        return names
