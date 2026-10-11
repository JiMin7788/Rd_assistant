"""Gear-deck live bot: perception.gear + policy.gear + input.inject.

DRY-RUN by default (prints what it would do, injects nothing). --execute to play.

Per tick, first matching rule wins:
  1. hunt popup open           -> tap its yellow 사냥
  2. 다이스 초월 visible        -> tap it (immediately, user rule)
  3. power panel open          -> tap the gear card N times, then close
  4. HP->SP event token        -> tap it while HP stays >= 30 (each tap -20)
  5. 사냥 button visible        -> tap it
  6. board not complete        -> policy.gear.plan_next (summon / merge / supporter)
  7. after 초월 / complete      -> open the power panel every POWER_EVERY s (spend SP on gears)
A merge whose two cells did not change is banned until either die changes (wrong pip read).
Board actions need two identical consecutive reads (a single misread frame flipped a
die to Adjust and triggered the supporter in the 2026-10-07 dry run), and "transcended"
needs >= 3 post-초월 gear colours on two consecutive reads (one teal gear misread as
grey switched on gear-gear merges before 초월 in the same run).
Field-effect banners are OCR'd: "낮은 눈금 3개 파괴 + 최고 눈금 복제" keeps a gear on top
until it fires, "60초 후 보유 SP만큼 획득" holds power-ups, "부족할 때 소환 보너스" spams 소환.
Stops (does nothing) when the frame is not a battle or the window moved.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.capture.live import LiveGrabber
from rdom.input.inject import Injector, cell_uv
from rdom.perception.board import is_battle, is_game_over
from rdom.perception import collect
from rdom.perception.gear import (read_board, ui_state, UI, GEAR_VARIANTS,
                                  banner_present, banner_text, effect_kind)
from rdom.policy.gear import evaluate, plan_next

SUPPORT_CD = 130.0
POWER_EVERY = 20.0
POWER_TAPS = 6
SUMMON_GAP = 0.5


def fmt(b):
    return " ".join("..." if d["type"] == "empty" else f"{d['type'][:2]}{d['pip']}" for d in b)


def _keepfmt(ev):
    """B2 De1 -- counts of the kept non-gear dice."""
    return " ".join(f"{t[:2] if t != 'Bubble' else 'B'}{n}" for t, n in ev["kept"].items())


def play(g, inj, minutes=30, tick=0.6):
    """Play the battle on screen until game over / window move / timeout.
    Returns "game_over", "moved" or "timeout". Per-game counters in play.stats."""
    play.stats = stats = {"merges": 0, "fails": 0, "support": 0, "complete": False}
    # completion rule of the deck in play (config/deck.toml [keep]), re-read every game
    import rdom.policy.gear as _pg
    print("deck keep:", _pg.load_deck(os.path.join(os.path.dirname(__file__), "..", "config", "deck.toml")), flush=True)
    tap = lambda k: inj.tap(*UI[k])
    transcended = False
    support_last = -1e9; power_last = -1e9; summon_last = -1e9; hunt_last = -1e9
    banned = {}                       # (from, to) -> (from die, to die) when it failed
    pending = None                    # (from, to, before-board) of the last merge
    prev_sig = None; post_hits = 0
    acted_at = -1e9
    doom_mem = {}                      # cell -> [corner base, centre seen] (2026-10-09)
    hpsp_last = -1e9; hpsp_est = 999; hp_seen = None
    ocr_last = -1e9; clone_until = -1e9; hold_power_until = -1e9; bonus_until = -1e9
    t_end = time.monotonic() + minutes * 60
    print(f"gear bot {'EXECUTE' if inj.execute else 'DRY-RUN'}", flush=True)

    while time.monotonic() < t_end:
        time.sleep(tick)
        try:
            if g.window_moved():
                print("window moved -- stopping"); return "moved"
        except OSError:
            continue
        f = g.grab(); now = time.monotonic()
        if is_game_over(f):
            print("game over"); return "game_over"
        from rdom.perception.gear import tactic_sp1000_card
        card = tactic_sp1000_card(f)                   # card order is random: read it
        if card:
            print(f"tactic screen -> 즉시 SP1000 at v={card[1]}", flush=True)
            inj.tap(*card); time.sleep(1.2); continue
        ui = ui_state(f)

        if ui["hunt_popup"]:
            print("hunt popup -> 사냥"); tap("hunt_popup_ok"); continue
        if ui["transcend"]:
            from rdom.perception.gear import transcend_tap
            uv = transcend_tap(f)
            print(f"초월! tap {uv[0]:.3f},{uv[1]:.3f}"); inj.tap(*uv); transcended = True; continue
        if ui["power_panel"]:
            from rdom.perception.gear import power_buttons
            btn = power_buttons(f)[0]                  # leftmost = gear
            print(f"power panel -> gear x{POWER_TAPS}, close", flush=True)
            for _ in range(POWER_TAPS):
                inj.tap(*btn); time.sleep(0.15)
            for _ in range(4):                         # make sure it really closes
                tap("power_close"); time.sleep(0.6)
                if not ui_state(g.grab())["power_panel"]:
                    break
            power_last = now; continue
        if ui["hpsp"]:
            # each tap costs HP 20; keep HP >= 30 (user 2026-10-08: at HP <= 20 a field
            # effect can turn dice into random +1-pip dice). Unreadable HP -> no tap.
            # the HP number updates a beat after the tap: two taps both read "50" and
            # took HP to 10 (2026-10-08). Gap the taps and trust our own -20 estimate.
            from rdom.perception.gear import read_hp
            hp = read_hp(f)
            # OCR can drop a digit ("150" read as "50", 2026-10-09): only trust a value
            # read twice in a row
            hp_prev, hp_seen = hp_seen, hp
            if hp is None or hp != hp_prev:
                hp = None
            if hp is not None and now - hpsp_last < 15.0:
                hp = min(hp, hpsp_est)
            if hp is not None and hp - 20 >= 30 and now - hpsp_last >= 3.0:
                print(f"HP->SP token (HP {hp})"); tap("hpsp")
                hpsp_last = now; hpsp_est = hp - 20; continue
        if ui["hunt"] and now - hunt_last > 3.0:
            print("hunt"); tap("hunt"); hunt_last = now; continue
        if not is_battle(f):
            continue                                   # menu / banner over the summon button

        # field-effect banner: OCR it (at most every 3 s) and arm the reaction
        if now - ocr_last > 3.0 and banner_present(f):
            ocr_last = now; kind = effect_kind(banner_text(f))
            if kind == "destroy3_clone_max" and now > clone_until:
                print("EFFECT: destroy 3 lowest + clone max in ~40s -> keep a gear on top")
                clone_until = now + 45
            elif kind == "sp_double_later" and now > hold_power_until:
                print("EFFECT: SP doubles in 60s -> holding power-ups"); hold_power_until = now + 65
            elif kind == "summon_bonus_when_short" and now > bonus_until:
                # NOT spammed: tapping 소환 on a full field ("필드에 공간이 부족합니다")
                # broke 11 merges in 60 s (2026-10-08 game). Normal summons on empty
                # cells already collect the bonus.
                print("EFFECT: summon bonus when short (no action)"); bonus_until = now + 60

        b = read_board(f)
        sig = tuple((d["type"], d["pip"]) for d in b)
        stable = sig == prev_sig; prev_sig = sig
        collect.maybe_save(f, b, stable)              # training data (부패 etc.), every 15 s
        post = sum(d["variant"] in GEAR_VARIANTS[1:] for d in b)
        post_hits = post_hits + 1 if post >= 3 else 0
        if post_hits >= 2 and not transcended:
            print("transcended (gear colours changed)"); transcended = True
        bc = {d["cell"]: d for d in b}
        # Doom: the centre pip is only drawn in some countdown phases, so remember it
        # for the die's lifetime (same cell, same corner pattern) once it was seen
        for d in b:
            c = d["cell"]
            if d["type"] != "Doom":
                if d["type"] != "junk":
                    doom_mem.pop(c, None)
                continue
            base = 1 if d["pip"] <= 1 else (d["pip"] // 2) * 2
            m = doom_mem.get(c)
            if m is None or m[0] != base:
                m = doom_mem[c] = [base, False]
            if d.get("doom_centre", 0) > 0.8 and base > 1:
                m[1] = True
            if m[1]:
                d["pip"] = base + 1
        # type only: a flickering pip read cleared a pip-keyed ban and the same misread
        # Adjust-4 pair was retried 26x (2026-10-08); cap at 90 s for real changes
        cellsig = lambda c: bc[c]["type"]
        if pending:                                    # verify the last merge took effect
            fr, to, before = pending; pending = None
            if all(bc[c]["type"] == before[c]["type"] and bc[c]["pip"] == before[c]["pip"]
                   for c in (fr, to)):
                # banned until either die changes: a timed ban retried the same
                # misread Adjust-3 pair 11x in the 2026-10-07 bot game
                banned[(fr, to)] = (cellsig(fr), cellsig(to), now + 90.0)
                print(f"   merge {fr}->{to} had no effect -> banned until those dice change")
                stats["fails"] += 1
        banned = {k: v for k, v in banned.items()
                  if v[:2] == (cellsig(k[0]), cellsig(k[1])) and now < v[2]}

        ev = evaluate(b)
        if ev["complete"]:
            stats["complete"] = True
        if not stable and not ev["empty"]:
            continue                                   # wait for a confirming read
        if ev["unknown"] > 3:
            continue                                   # popup/banner covering the board
        if ((transcended or ev["complete"]) and now - power_last > POWER_EVERY
                and now > hold_power_until):
            # aggressive merging never idles -> power up on a timer, not only when idle
            print(f"power-up (G{ev['gears']} {_keepfmt(ev)} avg{ev['gear_avg']} "
                  f"{'complete' if ev['complete'] else ''})"); tap("power_open"); power_last = now
            continue

        act = plan_next(b, transcended=transcended,
                        support_ready=now - support_last >= SUPPORT_CD, banned=set(banned),
                        clone_alert=now < clone_until)
        if act["op"] == "summon":
            if now - summon_last >= SUMMON_GAP:
                tap("summon"); summon_last = now; acted_at = now
        elif act["op"] == "merge":
            print(f"{fmt(b)} | G{ev['gears']} {_keepfmt(ev)} clu{ev['largest_cluster']} "
                  f"avg{ev['gear_avg']} -> merge {act['from']}->{act['to']}", flush=True)
            inj.swipe(*cell_uv(act["from"]), *cell_uv(act["to"]))
            pending = (act["from"], act["to"], bc); acted_at = now; stats["merges"] += 1
        elif act["op"] == "wait" and now - power_last > POWER_EVERY and now > hold_power_until:
            # nothing to do on the board -> spend SP on gears (user also powers up
            # before the field is complete; a stuck board sat on 168k SP 2026-10-07)
            print(f"idle ({act.get('why')}) -> power-up"); tap("power_open"); power_last = now
        elif act["op"] == "support":
            print(f"{fmt(b)} -> supporter <- {act['from']}", flush=True)
            inj.swipe(*cell_uv(act["from"]), *UI["support"], dur_ms=400)
            support_last = now; acted_at = now; stats["support"] += 1
    return "timeout"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="really inject input")
    ap.add_argument("--tick", type=float, default=0.6)
    ap.add_argument("--minutes", type=float, default=30)
    a = ap.parse_args()
    g = LiveGrabber()
    try:
        play(g, Injector(execute=a.execute), a.minutes, a.tick)
    finally:
        g.close()


if __name__ == "__main__":
    main()
