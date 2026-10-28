"""Support-deck per-tick players: shared skeleton (BasePlayer) and the collect-mode player.

BasePlayer.tick order, first match wins (reference: tools/gear_bot.py play()):
  window moved -> stop; game over -> stop; tactic card -> tap it; hunt popup -> tap its 사냥;
  power panel -> subclass hook; hunt button -> tap (>= 3 s apart); non-battle -> nothing;
  then the data cadence (cells 15 s, full frame 30 s) and the subclass battle_tick.
CollectPlayer only summons, takes one power-panel snapshot and saves training data. It never
touches the board, never taps hpsp/transcend and never buys a power-up.
Importing this module has no side effects.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception import board, gear, score, support

CELLS_EVERY = 15.0
FRAME_EVERY = 30.0
HUNT_EVERY = 3.0
SUMMON_GAP = 1.0
PANEL_AT = 120.0               # battle seconds before the one power-panel snapshot
PANEL_CLOSE_TRIES = 4


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
