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
from rdom.notify.room_state import write_room
from rdom.perception.board import (is_battle, is_game_over, is_lobby, read_speed,
                                   has_popup_close, has_modal_x, is_exit_dialog, is_coop_room,
                                   is_friend_menu)
from rdom.input.inject import CLOSE_X_UV, CANCEL_UV, MODAL_X_UV


def network_error(f):
    """The 알림 dialog with a single yellow 확인 at v~0.627 over a dark panel."""
    import cv2
    h, w = f.shape[:2]; W = round(h * 9 / 16)
    btn = cv2.cvtColor(f[int(0.605*h):int(0.650*h), int(0.30*W):int(0.70*W)], cv2.COLOR_RGB2HSV)
    yellow = ((btn[..., 0] >= 18) & (btn[..., 0] <= 35) & (btn[..., 1] > 120) & (btn[..., 2] > 150)).mean()
    panel = cv2.cvtColor(f[int(0.40*h):int(0.55*h), int(0.10*W):int(0.90*W)], cv2.COLOR_RGB2HSV)
    dark = (panel[..., 2] < 60).mean()
    return yellow > 0.5 and dark > 0.6
from rdom.perception import gear
from tools.bot_live import exit_to_lobby
from tools.gear_bot import play
from rdom.notify.discord import send_status

ap = argparse.ArgumentParser(); ap.add_argument("--until", default="23:59", help="HH:MM local (default: run all day)")
a = ap.parse_args()
hh, mm = map(int, a.until.split(":"))
now = datetime.datetime.now(); deadline = now.replace(hour=hh, minute=mm, second=0)
if deadline < now: deadline += datetime.timedelta(days=1)
LOG = r"C:\dev\rdom\data\gear_rounds.jsonl"
PAUSE = r"C:\dev\rdom\data\PAUSE"
STOP = r"C:\dev\rdom\data\STOP"                    # /종료 (Discord): end cleanly between games

g = LiveGrabber(); inj = Injector(execute=True)
fails = 0; rnd = 0
send_status(f"▶ 봇 시작 (종료 예정 {deadline:%H:%M})")
try:
    while datetime.datetime.now() < deadline:
        # pause switch: "봇 일시정지.bat" creates data/PAUSE, "봇 재개.bat" removes it.
        # Checked only between games, so the game in progress is always finished.
        if os.path.exists(STOP):
            os.remove(STOP); send_status("⏹ 종료 요청 -- 봇 종료"); break
        if os.path.exists(PAUSE):
            send_status("⏸ 일시정지 -- 판 사이에서 대기 중 (봇 재개.bat 로 재개)")
            while os.path.exists(PAUSE) and not os.path.exists(STOP) and datetime.datetime.now() < deadline:
                time.sleep(2)
            if os.path.exists(STOP):
                continue
            send_status("▶ 재개")
        rnd += 1
        print(f"=== round {rnd} ({datetime.datetime.now():%H:%M}) ===", flush=True)
        if g.window_moved():
            print("window moved -- stop"); send_status("⛔ 에뮬레이터 창이 움직여서 정지", g.grab()); break
        f = g.grab()
        if is_game_over(f):
            exit_to_lobby(g, inj); time.sleep(3); f = g.grab()
        # shop/event popups open by themselves on the lobby after a game (재설계 패키지,
        # 2026-10-08): close them with their X before starting a room
        unknown = 0; launches = 0
        for _ in range(30):
            # game closed (emulator on the launcher home screen, 2026-10-11): start it
            # again; BACK / taps on the home screen would never get back to the lobby
            if inj.game_in_front() is False:
                if launches >= 2:
                    print("game does not start -- give up this round", flush=True); break
                launches += 1
                print(f"게임이 꺼져 있음 -- 랜덤다이스 실행 ({launches}/2)", flush=True)
                send_status("🔄 게임이 꺼져 있어서 다시 실행합니다")
                inj.launch_game()
                # wait for a screen we know -- never BACK during splash/loading (it can
                # close the game again)
                t_l = time.monotonic()
                while time.monotonic() - t_l < 120:
                    time.sleep(3.0); f = g.grab()
                    if (is_lobby(f) or has_popup_close(f) or has_modal_x(f) or network_error(f)
                            or is_exit_dialog(f) or is_battle(f) or is_coop_room(f)):
                        break
                print(f"  loaded after {time.monotonic() - t_l:.0f}s", flush=True)
                unknown = 0; continue
            # popups first: a shop popup's green buy button sits where the lobby's 협동
            # button is (스텝업 패키지, 2026-10-10), so never decide "lobby" under a popup
            # the 친구와 하기 menu is a fine start too: open_room_and_wait taps 방 생성 there
            if (is_battle(f) or is_coop_room(f) or is_friend_menu(f)
                    or (is_lobby(f) and not has_popup_close(f))):
                break
            if network_error(f):
                # "네트워크 에러가 발생하여 게임을 재시작합니다." -- its only button is 확인;
                # the game then reloads (shop popups follow), 2026-10-09
                print("네트워크 에러 -- 확인, waiting for reload", flush=True)
                inj.tap(0.50, 0.627); time.sleep(8.0); f = g.grab(); continue
            if is_exit_dialog(f):
                print("종료 확인창 -- 취소", flush=True); inj.tap(*CANCEL_UV)
            elif has_popup_close(f):
                print("팝업 -- X 닫기", flush=True); inj.tap(*CLOSE_X_UV)
            elif is_game_over(f):
                exit_to_lobby(g, inj)
            elif has_modal_x(f) and unknown < 3:
                unknown += 1                         # BACK does not close these modals
                print(f"modal -- X 닫기 ({unknown}/3)", flush=True); inj.tap(*MODAL_X_UV)
            elif unknown < 3:
                # some other popup / screen without the bottom X: Android BACK closes
                # game popups (on the lobby it opens the exit dialog, cancelled above).
                # Never tap blind -- a popup is full of buy buttons.
                # A loading / transition screen is "unknown" too and BACK there can close
                # the game (2026-10-11, right after a relaunch): give it 5 s first.
                time.sleep(5.0); f2 = g.grab()
                if (is_lobby(f2) or has_popup_close(f2) or has_modal_x(f2) or is_battle(f2)
                        or is_coop_room(f2) or is_exit_dialog(f2) or network_error(f2)):
                    f = f2; continue
                unknown += 1
                print(f"unknown screen -- BACK ({unknown}/3)", flush=True); inj.back()
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
                    print("!! 3 failed rounds in a row -- stopping")
                    send_status("⛔ 방 만들기 3회 연속 실패 -- 정지. 화면 확인 필요", g.grab()); break
                time.sleep(5); continue
            t0 = time.monotonic()
            while not is_battle(g.grab()):
                if time.monotonic() - t0 > 90: break
                time.sleep(1.0)
            for _ in range(30):
                if read_speed(g.grab()) is not None: break
                time.sleep(0.5)
            print("배속 tap (once)", flush=True); inj.tap(*SPEED_UV)
            send_status(f"🎮 {rnd}판 시작")
        fails = 0
        rl = gear.reload_if_changed()
        if rl: print("models reloaded:", rl, flush=True)
        t_start = time.perf_counter()
        res = play(g, inj, minutes=40)
        t_end = time.perf_counter()
        st = getattr(play, "stats", {})
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"round": rnd, "t_start": t_start, "t_end": t_end, "result": res,
                                 "wall_end": datetime.datetime.now().isoformat(),
                                 "stats": {k: st.get(k) for k in ("merges", "fails", "support", "complete")}}) + "\n")
        print("battle result:", res, flush=True)
        write_room(None, "closed")                      # reservation turn is over
        send_status(f"🏁 {rnd}판 종료 · {(t_end - t_start)/60:.1f}분\n합성 {st.get('merges', 0)}회 · "
                    f"실패 {st.get('fails', 0)}회 · 서포터 {st.get('support', 0)}회 · "
                    f"필드 완성 {'O' if st.get('complete') else 'X'}")
        if res == "moved": break
        if res == "game_over":
            time.sleep(3.0); print("로비로 가기:", exit_to_lobby(g, inj), flush=True); time.sleep(3.0)
finally:
    g.close()
print("loop done", flush=True)
send_status("■ 봇 종료 (예정 시간 도달)")
