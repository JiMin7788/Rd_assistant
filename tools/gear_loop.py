"""Repeat gear-deck coop rounds until a deadline: lobby -> 방 생성 (no invite) ->
wait for a joiner -> 협동 시작 -> 배속 once -> bot plays -> 로비로 가기 -> repeat.
Models are hot-reloaded before every round (training runs alongside). Each round's
start/end (perf_counter, same clock as the recorder) goes to data/gear_rounds.jsonl.
Stops after 3 failed rounds in a row (fix the cause, don't loop blindly).

  python tools/gear_loop.py --until 13:23
"""
import argparse, datetime, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from rdom.capture.live import LiveGrabber
from rdom.input.inject import Injector, SPEED_UV
from rdom.input.friend_coop import open_room_and_wait
from rdom.perception.board import (is_battle, is_game_over, is_lobby, read_speed,
                                   has_popup_close, has_modal_x, is_exit_dialog, is_coop_room)
from rdom.input.inject import CLOSE_X_UV, CANCEL_UV
from rdom.perception import gear
from tools.bot_live import exit_to_lobby
from tools.gear_bot import play

ap = argparse.ArgumentParser(); ap.add_argument("--until", required=True, help="HH:MM local")
a = ap.parse_args()
hh, mm = map(int, a.until.split(":"))
now = datetime.datetime.now(); deadline = now.replace(hour=hh, minute=mm, second=0)
if deadline < now: deadline += datetime.timedelta(days=1)
LOG = r"C:\dev\rdom\data\gear_rounds.jsonl"

g = LiveGrabber(); inj = Injector(execute=True)
fails = 0; rnd = 0
try:
    while datetime.datetime.now() < deadline:
        rnd += 1
        print(f"=== round {rnd} ({datetime.datetime.now():%H:%M}) ===", flush=True)
        if g.window_moved():
            print("window moved -- stop"); break
        f = g.grab()
        if is_game_over(f):
            exit_to_lobby(g, inj); time.sleep(3); f = g.grab()
        # shop/event popups open by themselves on the lobby after a game (재설계 패키지,
        # 2026-10-08): close them with their X before starting a room
        for _ in range(6):
            if is_battle(f) or is_lobby(f) or is_coop_room(f):
                break
            if is_exit_dialog(f):
                print("종료 확인창 -- 취소", flush=True); inj.tap(*CANCEL_UV)
            elif has_popup_close(f):
                print("팝업 -- X 닫기", flush=True); inj.tap(*CLOSE_X_UV)
            elif is_game_over(f):
                exit_to_lobby(g, inj)
            else:
                break
            time.sleep(1.5); f = g.grab()
        if not is_battle(f):
            left = (deadline - datetime.datetime.now()).total_seconds()
            ok = open_room_and_wait(g, inj, timeout=max(60, min(1800, left)))
            if ok is False:                         # nobody joined: keep waiting, not a fault
                print("nobody joined -- waiting again", flush=True); continue
            if not ok:
                fails += 1; print(f"round did not start ({ok}); fails={fails}", flush=True)
                if fails >= 3:
                    print("!! 3 failed rounds in a row -- stopping"); break
                time.sleep(5); continue
            t0 = time.monotonic()
            while not is_battle(g.grab()):
                if time.monotonic() - t0 > 90: break
                time.sleep(1.0)
            for _ in range(30):
                if read_speed(g.grab()) is not None: break
                time.sleep(0.5)
            print("배속 tap (once)", flush=True); inj.tap(*SPEED_UV)
        fails = 0
        rl = gear.reload_if_changed()
        if rl: print("models reloaded:", rl, flush=True)
        t_start = time.perf_counter()
        res = play(g, inj, minutes=40)
        t_end = time.perf_counter()
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"round": rnd, "t_start": t_start, "t_end": t_end, "result": res,
                                 "wall_end": datetime.datetime.now().isoformat()}) + "\n")
        print("battle result:", res, flush=True)
        if res == "moved": break
        if res == "game_over":
            time.sleep(3.0); print("로비로 가기:", exit_to_lobby(g, inj), flush=True); time.sleep(3.0)
finally:
    g.close()
print("loop done", flush=True)
