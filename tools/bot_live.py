"""Live bot loop: grab the board -> read -> evaluate -> plan -> (optionally act).

  python tools/bot_live.py                 # one grab, dry-run (no injection)
  python tools/bot_live.py --loop 20        # 20 iterations, dry-run
  python tools/bot_live.py --loop 20 --execute   # SUPERVISED real injection

Aborts if the emulator window moves (coordinates would be invalid). Real
injection only with --execute; otherwise every action is printed, not sent.
"""
from __future__ import annotations
import argparse
import time

from rdom.capture.live import LiveGrabber
from rdom.perception.board import (read_board, read_board_stable, load_templates,
                                    is_battle, is_game_over, any_switch_ready,
                                    board_glare, read_speed,
                                    has_popup_close)
from rdom.policy.target import evaluate, plan_next
from rdom.input.inject import Injector


def progress_str(board):
    """Live arrangement accuracy: fixed cells (Predator #1,3,11 + Light) correct
    out of 8, plus n-cell resonance/bubble counts. Lets us SEE convergence."""
    from rdom.policy.target import FIXED, NCELLS, evaluate
    bc = {c["cell"]: c for c in board}
    fix_ok = sum(1 for cell, want in FIXED.items() if bc[cell]["type"] == want)
    p = evaluate(board)["pip_target"]
    res = sum(1 for c in NCELLS if bc[c]["type"] == "Resonance"
              and (p is None or bc[c]["pip"] == p))
    bub = sum(1 for c in NCELLS if bc[c]["type"] == "Bubble")
    return f"fixed {fix_ok}/8  reson {res}/3  bubble {bub}/1"


def show_board(board):
    for r in range(3):
        row = board[r*5:(r+1)*5]
        print("  " + "  ".join(f"#{c['cell']:2d} {c['type'][:4]:4s}{c['pip']}" for c in row))


def start_friend_coop(grab, inj, wait=1.5):
    """From the lobby: tap '친구와 하기' -> wait for the popup -> tap '방 생성'."""
    from rdom.input.inject import FRIEND_UV, CREATE_ROOM_UV
    print("tap 친구와 하기", flush=True)
    inj.tap(*FRIEND_UV)
    time.sleep(wait)
    print("tap 방 생성 (create room)", flush=True)
    inj.tap(*CREATE_ROOM_UV)
    grab.close()


def exit_to_lobby(grab, inj, tries=6):
    """Tap '로비로 가기' until the game-over screen is gone. The screen animates
    in, so a single early tap can miss the button -- retry until it takes."""
    from rdom.input.inject import LOBBY_UV
    for _ in range(tries):
        inj.tap(*LOBBY_UV)
        time.sleep(1.5)
        if not is_game_over(grab.grab()):
            return True
    return False


def switch_verified(inj, grab, tpls, frm, to, tries=10):
    """Drag the switch from #frm onto #to and confirm the swap by checking the
    switch LEFT #frm. The switch cooldown varies (user), so we retry through it
    rather than guess a timer -- but we verify on the source cell only, not the
    exact destination type: the destination often sits under Resonance's red glow
    and its read flickers, which would make an exact-pair check miss a swap that
    really happened and then re-swap it (undoing the placement). Once the switch
    has left #frm the swap is done -> stop (never re-swap)."""
    b0 = read_board_stable(grab, tpls, n=2)
    if b0[frm - 1]["type"] != "Switch":           # not actually a switch -> abort
        return False
    if b0[to - 1]["type"] == "Switch":            # target already a switch -> no-op
        return True
    for k in range(tries):
        inj.execute_action({"op": "switch", "from": frm, "to": to})
        time.sleep(0.5)
        if read_board_stable(grab, tpls, n=2)[frm - 1]["type"] != "Switch":
            return True                           # switch moved -> swap happened
        time.sleep(0.7)                           # still on #frm -> cooldown, retry
    return False


def _dismiss(inj, frame):
    """Close whatever is covering the battle. Press the popup's X when it has one
    (user 2026-09-27), and only fall back to a tap in the middle otherwise: the
    blind middle tap opened the 난이도 선택 map straight from the lobby and the bot
    then sat behind it, 배속 unreachable (2026-09-28)."""
    from rdom.input.inject import CLOSE_X_UV
    if has_popup_close(frame):
        inj.tap(*CLOSE_X_UV)
    else:
        inj.tap(0.50, 0.62)


def ensure_speed(grab, inj, target=2.0, tries=6, dt=0.2, warmup=16,
                 settle=2.5):
    """Tap 배속 until the button really reads `target` (user 2026-09-27: the
    speed-up must ALWAYS be on). A single blind tap was unreliable -- it can land
    while the battle is still loading, or on a frame where a popup covers the
    button -- and nothing checked afterwards, so a whole battle could run at 1.0x.

    Taps cycle 1.0 -> 1.5 -> 2.0 -> 1.0, so tapping blind is worse than not
    tapping: it lands on an unknown speed. The caption (perception.read_speed) is
    therefore WAITED for first -- it is not drawn while the battle animates in --
    and only then is the button tapped, re-reading after every tap.
    Returns the speed finally read (None if the caption never became legible)."""
    from rdom.input.inject import SPEED_UV
    cur = None
    for _ in range(warmup):                      # battle still loading -> no caption
        cur = read_speed(grab.grab())
        if cur is not None:
            break
        time.sleep(0.5)
    if cur is None:
        print("배속 caption unreadable -- one blind tap, re-checked after fill",
              flush=True)
        inj.tap(*SPEED_UV)
        return None
    for _ in range(tries):
        if cur >= target:
            print(f"배속 {cur}x", flush=True)
            return cur
        inj.tap(*SPEED_UV)
        # The caption lags its own tap (button animation), so poll until it
        # actually changes rather than reading once: a single read saw the
        # pre-tap value every time and kept tapping past 2.0x (2026-09-27).
        t_end = time.monotonic() + settle
        while time.monotonic() < t_end:
            got = read_speed(grab.grab())
            if got is not None and got != cur:
                cur = got
                break
            time.sleep(dt)
    print(f"배속 not confirmed (read {cur})", flush=True)
    return cur


def handle_tactic_screen(grab, inj):
    """At game start a "전술효과 선택" screen sometimes appears with 3 options; pick
    '즉시 SP1000 획득' (풍요의 시작, the 3rd) -- it has an orange coin icon on the
    left. Detect that icon and tap the 3rd box. Returns True if it acted. Also saves
    the frame the first time for detector calibration."""
    import cv2, os, numpy as np
    f = grab.grab(); H, W = f.shape[:2]
    # the 3 tactic options are DARK navy boxes; the empty battle board is bright tan.
    # require the 3rd box body to be dark AND its left icon to be orange (coins).
    box = f[int(0.57*H):int(0.67*H), int(0.30*W):int(0.68*W)]
    box_dark = float((cv2.cvtColor(box, cv2.COLOR_RGB2HSV)[..., 2] < 90).mean())
    icon = f[int(0.57*H):int(0.67*H), int(0.09*W):int(0.18*W)]
    hsv = cv2.cvtColor(icon, cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    coin = float((((hh <= 28) | (hh >= 168)) & (ss > 90) & (vv > 110)).mean())
    is_tactic = box_dark > 0.5 and coin > 0.15
    if is_tactic and not os.path.exists(r"C:\dev\rdom\_tactic_seen.png"):
        from PIL import Image as _I
        _I.fromarray(f).save(r"C:\dev\rdom\_tactic_seen.png")
    if is_tactic:
        print("tactic screen -> pick 즉시 SP1000", flush=True)
        inj.tap(0.50, 0.62); time.sleep(1.2)
        return True
    return False


def handle_bombs(grab, inj, tpls):
    """Detect and clear black bomb dice, confirming with a re-read so a transient
    dark animation frame is not a false bomb. Bombs merge into a pip-2 die, so a
    pair is merge+destroyed (never left as pip-2) and a lone bomb is destroyed.
    Returns True if it acted. Needs the Cheong skill (90s cd)."""
    if not inj.cheong_ready():
        return False
    board = read_board_stable(grab, tpls, n=2)
    if not any(c["type"] == "Bomb" for c in board):
        return False
    time.sleep(0.3)                              # confirm (animations look dark)
    chk = read_board(grab.grab(), tpls)
    bombs = [c["cell"] for c in chk if c["type"] == "Bomb"]
    if len(bombs) >= 2:
        print("bomb pair -> merge+destroy", flush=True)
        inj.execute_action({"op": "merge_destroy", "from": bombs[0], "to": bombs[1]})
        return True
    if len(bombs) == 1:
        print("bomb -> destroy", flush=True)
        inj.execute_action({"op": "destroy", "cell": bombs[0]})
        return True
    return False


def _collect_crops(frame, seen):
    """Save the 15 cell crops with a confident colour-rule label (ambiguous ->
    _unlabeled) for training data. Called during play so the board is DIVERSE
    (the bot churns it), unlike a static summon-only dump. Dedupes near-identical
    crops via a coarse hash so we don't flood with copies of a frozen board."""
    import uuid, os, cv2
    from PIL import Image
    from rdom.perception.board import (cell_box, COLS, ROWS, OPP_COLS, OPP_ROWS,
                                       _debuff_cast)
    from rdom.perception.features import strict_label, CROP_ROOT as ROOT
    f = _debuff_cast(frame); H, W = f.shape[:2]
    # Both fields (user 2026-09-28). The partner's board doubles the crops per
    # frame and adds dice we never build ourselves, so the recognizer sees types
    # and effect overlays our own target layout never produces. It is kept in a
    # SEPARATE root so training can weigh or drop it -- the top board is drawn
    # slightly differently (smaller glow, partner's own buffs) and mixing it into
    # the same folders would hide that.
    for root, cols, rows in ((ROOT, COLS, ROWS), (ROOT + "_opp", OPP_COLS, OPP_ROWS)):
        for rv in rows:
            for cu in cols:
                x0, y0, x1, y1 = cell_box(cu, rv, W, H)
                crop = f[y0:y1, x0:x1]
                small = cv2.resize(crop, (8, 8)).astype(int) // 32   # coarse hash
                key = small.tobytes()
                if key in seen:
                    continue
                seen.add(key)
                lab = strict_label(crop) or "_unlabeled"
                d = os.path.join(root, lab); os.makedirs(d, exist_ok=True)
                Image.fromarray(crop).save(os.path.join(d, uuid.uuid4().hex[:10] + ".png"))


def play_battle(grab, inj, tpls, fill_secs=30.0, place_dt=1.0, max_iters=1500,
                collect=False):
    """Play one battle to the game-over screen, then go to lobby.

    Summon cadence (user 2026-09-16):
      1) FILL: after the speed toggle, tap Summon once/sec for `fill_secs` to fill
         the board for early defense.
      2) WORK: stop the steady summoning. Each cycle read the field; if there is
         work to do, summon -> perform the action -> summon, so a cell a
         merge/destroy frees is refilled at once and no summon taps are wasted
         (the old parallel thread fired ~370 taps/game, ~355 of them onto a full
         board). Repeat until the layout is complete, then just keep it topped up.
    Only this loop grabs (one dxcam consumer). Stops only on the game-over screen;
    popups are tapped away.
    """
    from rdom.input.inject import SUMMON_UV, SPEED_UV
    from rdom.policy.target import evaluate, plan_next

    # game-start tactical-effect screen (probabilistic): pick 즉시 SP1000 first.
    for _ in range(4):
        if handle_tactic_screen(grab, inj):
            break
        time.sleep(0.5)

    def check_exit(frame):
        if is_game_over(frame):
            print("GAME OVER -- go to lobby", flush=True)
            exit_to_lobby(grab, inj); return True
        return False

    # 1) FILL phase -- one summon per second for fill_secs, board fills for defense.
    #    배속 is switched on from inside this loop: the caption does not exist while
    #    the battle animates in, so a blocking check before the fill could only tap
    #    blind and the battle ran its first 30s at 1.0x. Here the frame is already
    #    grabbed, so it costs one OCR per second and the speed goes on the moment
    #    the button appears -- without delaying a single summon.
    t_end = time.monotonic() + fill_secs
    n = 0
    speed = None
    while time.monotonic() < t_end:
        if grab.window_moved():
            print("!! window moved -- stopping", flush=True); return "ended"
        frame = grab.grab()
        if check_exit(frame):
            return "gameover"
        if is_battle(frame):
            inj.tap(*SUMMON_UV); n += 1
            if speed is None or speed < 2.0:
                got = read_speed(frame)
                if got is not None:
                    speed = got
                    if got >= 2.0:
                        print(f"배속 {got}x", flush=True)
                    else:
                        inj.tap(*SPEED_UV)       # 1.0 -> 1.5 -> 2.0, one step/sec
            handle_bombs(grab, inj, tpls)        # clear bombs even during the fill
        else:
            _dismiss(inj, frame)                 # popup/menu over the battle
        time.sleep(1.0)
    print(f"fill done ({n} summons) -- work phase", flush=True)
    ensure_speed(grab, inj)                      # re-confirm after the loading/popup phase

    # 2) WORK phase -- a per-cell BELIEF TRACKER drives everything (docs/07 Layer A).
    #    Each frame is one noisy observation; the tracker keeps a stable belief per
    #    cell and abstains on low-confidence (effect) frames, so the planner only ever
    #    acts on beliefs that survived several clean reads. This replaces the old
    #    locked/wrongrun/double-read-confirm machinery -- the tracker generalizes it to
    #    all 15 cells (a correct Predator needs 8 confident wrong frames to change; a
    #    just-swapped cell repairs in 1). Uncertain cells are passed as `locked` so the
    #    planner never moves a die it isn't sure about.
    from rdom.perception.tracker import CellTracker
    tracker = CellTracker()
    # A swap that did not take is retried by the planner forever unless we remember
    # it: 2026-10-01 the bot replanned "#13->#3" ~20 times in a row (each = up to 10
    # drags) while the board fell apart. Most likely the target is a pip-2 die read
    # as pip 1 (swaps need equal pips, and pip-2 reads are unreliable). So a failed
    # target is cooled down (treated as locked) and, if failures still pile up, the
    # game is judged broken and the run stops so the cause gets fixed (user rule).
    SWAP_COOLDOWN = 30.0                         # s a failed swap target stays locked
    ANOMALY_FAILS, ANOMALY_WINDOW = 6, 90.0      # >= N switch failures within window
    swap_cool = {}                               # cell -> monotonic time it unlocks
    fail_times = []
    last_action = None                           # action performed since the last grab
    seen_crops = set()                           # dedupe for --collect
    for it in range(max_iters):
        if grab.window_moved():
            print("!! window moved -- stopping", flush=True); break
        frame = grab.grab()
        if check_exit(frame):
            return "gameover"
        if not is_battle(frame):                 # popup/menu over the battle
            _dismiss(inj, frame)
            last_action = None                   # our tap is not a board action
            time.sleep(place_dt); continue
        if it and it % 30 == 0:
            # Re-check 배속. Setting it once at the start is not enough -- a battle
            # can come back at 1.5x (a boss/field-event screen resets it, or the
            # first taps land while the caption is still hidden) and nothing was
            # watching, so a whole game ran slow (user 2026-09-28: "배속 왜 자꾸
            # 까먹냐"). One OCR every ~30 cycles costs nothing.
            ensure_speed(grab, inj)
        if collect:
            _collect_crops(frame, seen_crops)    # gather diverse training crops
        obs = read_board(frame, tpls)            # ONE frame, per-cell (type, conf)
        tracker.update(obs, last_action)         # fold into beliefs (action-aware)
        last_action = None
        board = tracker.belief_board()           # stable belief -> plan on this
        uncertain = tracker.uncertain()          # cells not to touch (unseen/low-conf)
        now = time.monotonic()
        cooling = {c for c, t in swap_cool.items() if t > now}
        uncertain = set(uncertain) | cooling
        if evaluate(board)["complete"]:
            print(f"COMPLETE -- {progress_str(board)}", flush=True)
            inj.tap(*SUMMON_UV)                  # keep the board topped up (defense)
            time.sleep(place_dt); continue
        print(f"progress: {progress_str(board)}  uncertain={len(uncertain)}", flush=True)
        # Plan on the belief board; uncertain cells are locked. Switch cooldown varies,
        # so don't gate on a timer -- switch_verified() retries through the real one.
        action = plan_next(board, cheong_ready=inj.cheong_ready(), switch_ready=True,
                           locked=uncertain)
        op = action and action.get("op")
        if op == "switch":
            # No double-read needed: the belief is already stable across frames, so a
            # planned swap is real, not a one-frame wobble.
            print(f"place: switch {action.get('why','')} "
                  f"#{action['from']}->#{action['to']}", flush=True)
            inj.tap(*SUMMON_UV)                  # refill any empty first
            ok = switch_verified(inj, grab, tpls, action["from"], action["to"])
            if not ok:
                print("    switch did not take (retries exhausted) -- "
                      f"#{action['to']} cooled {SWAP_COOLDOWN:.0f}s", flush=True)
                now = time.monotonic()
                swap_cool[action["to"]] = now + SWAP_COOLDOWN
                fail_times = [t for t in fail_times if now - t < ANOMALY_WINDOW] + [now]
                if len(fail_times) >= ANOMALY_FAILS:
                    print(f"!! ANOMALY: {len(fail_times)} switch failures in "
                          f"{ANOMALY_WINDOW:.0f}s -- game judged broken, stopping "
                          f"({progress_str(board)})", flush=True)
                    return "anomaly"
            inj.tap(*SUMMON_UV)
            last_action = action                 # tell the tracker the swap happened
        elif op in ("merge", "destroy", "merge_destroy"):
            print(f"place: {op} {action.get('why','')}", flush=True)
            inj.tap(*SUMMON_UV)                  # summon -> refill any empty
            inj.execute_action(action)           # perform the event
            inj.tap(*SUMMON_UV)                  # summon -> refill the freed cell
            last_action = action                 # tracker frees the source cell
        else:
            inj.tap(*SUMMON_UV)                  # nothing to place -> keep full
        time.sleep(place_dt)
    return "ended"


def autoplay(grab, inj, rounds=1, interval=1.0, collect=False):
    """Full loop: from lobby, start random 협동, play the battle, return to lobby,
    repeat. `rounds` battles. collect=True gathers training crops across the games."""
    from rdom.input.inject import COOP_UV
    tpls = load_templates()
    for r in range(rounds):
        print(f"=== round {r+1}/{rounds}: start 협동 ===", flush=True)
        inj.tap(*COOP_UV); time.sleep(1.5)
        entered = False
        for _ in range(40):                      # wait for matchmaking
            if is_battle(grab.grab()):
                entered = True; break
            time.sleep(1.0)
        if not entered:
            print("no battle (matchmaking failed) -- stopping", flush=True); break
        print("battle entered", flush=True)
        play_battle(grab, inj, tpls, place_dt=interval, collect=collect)
        time.sleep(4.0)                          # settle on lobby after game-over
    grab.close()


def summon_spam(grab, inj, interval, max_iters):
    """Keep the field full: tap Summon once per interval while in a battle, from
    battle-start until the battle ends. No recognition needed -- a full board
    removes the empty-vs-Predator ambiguity and cuts computation (user request)."""
    from rdom.input.inject import SUMMON_UV, LOBBY_UV
    for _ in range(max_iters):
        if grab.window_moved():
            print("!! window moved -- stopping", flush=True)
            break
        frame = grab.grab()
        # The ONLY stop signal is the game-over screen. The summon button
        # vanishing just means a boss/field-effect popup is up (controls blocked)
        # -- the battle is still going, so we wait, we do not stop.
        if is_game_over(frame):
            print("GAME OVER -- tapping 'go to lobby'", flush=True)
            exit_to_lobby(grab, inj)
            break
        if is_battle(frame):
            inj.tap(*SUMMON_UV)
            print("summon", flush=True)
        else:
            print("no summon button (popup) -- waiting", flush=True)
        time.sleep(interval)
    grab.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=1)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--execute", action="store_true", help="send real touches")
    ap.add_argument("--summon-spam", action="store_true",
                    help="just tap Summon 1/sec until the battle ends")
    ap.add_argument("--start-coop", action="store_true",
                    help="from lobby: tap 친구와 하기 then 방 생성")
    ap.add_argument("--start-friend", metavar="NAME",
                    help="full 친구와 하기 flow: invite NAME then start")
    ap.add_argument("--autoplay", action="store_true",
                    help="full loop: lobby->협동->play->lobby, --loop rounds")
    ap.add_argument("--play-battle", action="store_true",
                    help="play the CURRENT battle (phased summon + placement)")
    ap.add_argument("--collect", action="store_true",
                    help="save training crops while playing (diverse boards)")
    args = ap.parse_args()

    if args.autoplay:
        autoplay(LiveGrabber(), Injector(execute=args.execute),
                 rounds=args.loop if args.loop > 1 else 1, interval=args.interval,
                 collect=args.collect)
        return
    if args.play_battle:
        g = LiveGrabber()
        play_battle(g, Injector(execute=args.execute), load_templates(),
                    place_dt=args.interval, collect=args.collect)
        g.close()
        return
    if args.start_friend:
        from rdom.input.friend_coop import start_friend_coop as ff
        ff(LiveGrabber(), Injector(execute=args.execute), args.start_friend,
           max_retries=args.loop if args.loop > 1 else 3)
        return
    if args.start_coop:
        start_friend_coop(LiveGrabber(), Injector(execute=args.execute))
        return
    if args.summon_spam:
        summon_spam(LiveGrabber(), Injector(execute=args.execute),
                    interval=max(0.5, args.interval), max_iters=args.loop)
        return

    grab = LiveGrabber()
    tpls = load_templates()
    inj = Injector(execute=args.execute)
    mode = "EXECUTE (real touches)" if args.execute else "dry-run"
    print(f"live bot -- {mode}, {args.loop} iteration(s)\n")

    for it in range(args.loop):
        if grab.window_moved():
            print("!! window moved -- aborting (coordinates invalid)")
            break
        frame = grab.grab()
        if not is_battle(frame):
            print(f"[iter {it+1}] not in a battle (menu/lobby/popup) -- skipping")
            if it < args.loop - 1:
                time.sleep(args.interval)
            continue
        board = read_board(frame, tpls)
        print(f"[iter {it+1}] board:")
        show_board(board)
        ev = evaluate(board)
        print(f"  complete={ev['complete']} pip_target={ev['pip_target']}"
              f" violations={len(ev['violations'])}")
        for v in ev["violations"][:6]:
            print("   ", v)
        if ev["complete"]:
            print("  target reached -- nothing to do")
            break
        action = plan_next(board, cheong_ready=inj.cheong_ready())
        print(f"  action: {action}")
        if action:
            inj.execute_action(action)
        if it < args.loop - 1:
            time.sleep(args.interval)
    grab.close()


if __name__ == "__main__":
    main()
