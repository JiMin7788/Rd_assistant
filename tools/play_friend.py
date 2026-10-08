"""Run the bot in 친구와 하기 (play-with-friend) coop, end to end, forever.

Closes the loop that tools/play.py left to the human: instead of waiting for a
battle the user starts, this navigates the lobby itself and repeats --

  로비 -> 친구와 하기 -> 방 생성 -> 친구 초대(NAME, OCR) -> 수락 대기 -> 협동 시작
  -> 전투 감지 -> 배속 확인 -> play_battle(소환 채우기 + eager 배치) -> 종료 -> 로비 -> 반복

Runs until stopped (Ctrl-C) or the emulator window moves. A round that fails to
start (friend offline, tap missed) is NOT fatal: the screen is unwound with BACK
until the lobby is back and the next round retries -- an infinite run must not
die on one bad navigation. If a battle is already on screen when it starts, that
battle is played first and the loop begins after it.

  python tools/play_friend.py [NAME] [rounds]     NAME 대변먹는자, rounds 0 = 무한
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rdom.capture.live import LiveGrabber
from rdom.perception.board import (is_battle, is_game_over, is_lobby, is_exit_dialog,
                                   has_popup_close, has_modal_x, load_templates)
from rdom.input.inject import Injector, CANCEL_UV, CLOSE_X_UV, MODAL_X_UV
from rdom.input.friend_coop import start_friend_coop
from tools.bot_live import play_battle, exit_to_lobby

name = sys.argv[1] if len(sys.argv) > 1 else "대변먹는자"
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 0      # 0 = 무한 반복

g = LiveGrabber()
inj = Injector(execute=True)          # execute=True -> real taps/swipes
tpls = load_templates()


def moved():
    try:
        return g.window_moved()
    except OSError:
        return False


def frame():
    try:
        return g.grab()
    except Exception:
        return None


def to_lobby(tries=8):
    """Get back to the lobby: clear the result screen, then BACK out of any
    half-finished room/popup. Called before every round so one failed navigation
    cannot wedge the whole run. Returns False if a battle is up (caller plays it).

    BACK is only pressed on a screen we do NOT recognise -- on the lobby root it
    opens '게임을 종료하시겠습니까?', and a blind BACK loop walked straight into it
    (2026-09-27) leaving the bot tapping behind a dialog whose 확인 quits the game.
    Seeing that dialog is itself proof we are on the lobby: cancel it and stop.
    """
    for i in range(tries):
        f = frame()
        if f is None:
            time.sleep(1.0); continue
        if is_game_over(f):
            exit_to_lobby(g, inj); continue
        if is_exit_dialog(f):
            print("종료 확인창 -- 취소", flush=True)
            inj.tap(*CANCEL_UV); time.sleep(1.2)
            return True
        if is_battle(f):
            return False                        # a battle is up -- caller plays it
        if is_lobby(f):
            return True
        # Unknown screen. A shop/event popup opens by itself on the lobby and is
        # closed with its X (user 2026-09-27) -- but only if that X is really
        # there: blind-tapping it in the coop room hit 다이스 트리 and opened more
        # screens. Anything else (coop room, sub-menu) leaves with BACK, which is
        # safe here because the lobby itself was already ruled out above.
        if has_popup_close(f):
            print("팝업 -- X 닫기", flush=True)
            inj.tap(*CLOSE_X_UV)
        elif has_modal_x(f):
            # 친구와 하기 menu / coop room: BACK does nothing here, only the red X
            # top-right closes it (measured 2026-10-01).
            print("협동 창 -- X 닫기", flush=True)
            inj.tap(*MODAL_X_UV)
        else:
            inj.back()
        time.sleep(1.5)
    return True                                 # unknown screen -- the gated flow aborts if wrong


def play():
    """One battle. A capture failure (dxcam device lost) ends the ROUND, not the
    run: the next round's to_lobby() sees the battle still on screen and resumes
    it, so an infinite run heals itself instead of dying on a bad grab."""
    try:
        # collect=True: save labelled cell crops from BOTH fields while playing
        # (user 2026-09-28) -- training data for the recognizer rework, docs/07.
        res = play_battle(g, inj, tpls, place_dt=1.0, collect=True)
    except RuntimeError as e:
        print(f"capture failed ({e}) -- ending the round, will resume", flush=True)
        res = None
    if res == "anomaly":
        # The bot broke the game (e.g. a swap it can't make, retried forever).
        # Don't keep playing on a broken board or start new rounds on the same bug:
        # stop the whole run so the cause is fixed first (user 2026-10-01).
        raise SystemExit("ANOMALY -- run stopped, fix the cause before restarting")
    time.sleep(6.0)


def play_current():
    """Play the battle currently on screen (restart mid-battle, or a coop the
    friend started)."""
    print("battle on screen -- BOT PLAYING", flush=True)
    play()


r = 0
fails = 0
nav_fails = 0
try:
    f = frame()
    if f is not None and is_battle(f):
        play_current()
    while rounds == 0 or r < rounds:
        r += 1
        label = f"{r}/{rounds}" if rounds else str(r)
        print(f"=== round {label}: 친구와 하기 with {name} ===", flush=True)
        if moved():
            print("window moved -- stop", flush=True); break
        if not to_lobby():                      # already in a battle -> play it
            play_current(); continue
        ok = start_friend_coop(g, inj, name)
        if ok is None:
            # Navigation went off the expected screen. Retrying blindly is what
            # bounced the lobby between 난이도 선택 / 다이스 트리 (2026-10-01): a few
            # recoveries are fine, a streak means something is broken -> stop and
            # fix the cause first (user rule).
            nav_fails += 1
            if nav_fails >= 3:
                print(f"!! ANOMALY: navigation failed {nav_fails}x in a row -- "
                      "run stopped, fix the cause before restarting", flush=True)
                break
            print(f"navigation aborted ({nav_fails}/3) -- recover and retry", flush=True)
            time.sleep(3.0)
            continue
        nav_fails = 0
        if not ok:
            fails += 1
            print(f"coop did not start (fail {fails}) -- retry in 20s", flush=True)
            time.sleep(20.0)
            continue
        entered = False
        for _ in range(90):                     # loading screen -> battle, ~90s max
            if moved():
                print("window moved -- stop", flush=True); raise SystemExit
            f = frame()
            if f is not None and is_battle(f):
                entered = True; break
            time.sleep(1.0)
        if not entered:
            fails += 1
            print(f"battle never started (fail {fails}) -- retry", flush=True)
            continue
        fails = 0
        print("battle detected -- BOT PLAYING", flush=True)
        play()                                  # settles on the lobby afterwards
except KeyboardInterrupt:
    print("interrupted", flush=True)
finally:
    g.close()
print("DONE", flush=True)
