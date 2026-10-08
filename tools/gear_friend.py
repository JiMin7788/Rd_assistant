"""One gear-deck round with a friend: lobby -> 친구와 하기 -> invite NAME -> 협동 시작
-> gear bot plays (EXECUTE) -> 로비로 가기.

  python tools/gear_friend.py [NAME]      default 대변먹는자
  python tools/gear_friend.py --wait      create the room, invite nobody, wait for a joiner
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from rdom.capture.live import LiveGrabber
from rdom.input.inject import Injector
from rdom.input.friend_coop import start_friend_coop, open_room_and_wait
from rdom.perception.board import is_battle, read_speed
from rdom.input.inject import SPEED_UV
from tools.bot_live import exit_to_lobby
from tools.gear_bot import play

wait_mode = "--wait" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
name = args[0] if args else "대변먹는자"
g = LiveGrabber(); inj = Injector(execute=True)
try:
    if not is_battle(g.grab()):
        ok = open_room_and_wait(g, inj) if wait_mode else start_friend_coop(g, inj, name)
        print("coop start ->", ok, flush=True)
        if not ok:
            raise SystemExit("could not start the coop round")
        t0 = time.monotonic()
        while not is_battle(g.grab()):
            if time.monotonic() - t0 > 90:
                raise SystemExit("battle did not start within 90s")
            time.sleep(1.0)
        # 배속 is a per-player toggle (one player on = 1.5x, both = 2.0x, user
        # 2026-10-08): tap it exactly ONCE at the start of a game we started. Never
        # re-tap on a restart mid-game -- a second tap would turn our vote off.
        for _ in range(30):                      # caption is not drawn while loading
            if read_speed(g.grab()) is not None:
                break
            time.sleep(0.5)
        print("배속 tap (once)", flush=True); inj.tap(*SPEED_UV)
    print("battle -- BOT PLAYING", flush=True)
    res = play(g, inj, minutes=30)
    print("battle result:", res, flush=True)
    if res == "game_over":
        time.sleep(3.0)
        print("로비로 가기:", exit_to_lobby(g, inj), flush=True)
finally:
    g.close()
