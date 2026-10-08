"""Run the bot on USER-started battles.

Coop auto-start is unreliable (matchmaking finds no partner from a tap), so the human
starts each 협동 battle and the bot plays it with the current recognition + policy:
the CellTracker belief loop (docs/07 Layer A), Cheong reserved for bombs, and the
predator/fixed-cell protection. Window-handle hiccups (LDPlayer minimised/closed) are
tolerated, not fatal.

  python tools/play.py [rounds]      rounds default 20 (battles you start, in a row)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rdom.capture.live import LiveGrabber
from rdom.perception.board import is_battle, load_templates
from rdom.input.inject import Injector
from tools.bot_live import play_battle

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
g = LiveGrabber()
inj = Injector(execute=True)         # execute=True -> real taps/swipes
tpls = load_templates()


def moved():
    try:
        return g.window_moved()
    except OSError:
        return False


def grab():
    try:
        return g.grab()
    except Exception:
        return None


for r in range(rounds):
    print(f"=== waiting for battle {r+1}/{rounds} (start 협동 in the game) ===", flush=True)
    entered = False
    for _ in range(1800):                         # up to ~30 min for the human to start
        if moved():
            print("window moved -- stop", flush=True); g.close(); sys.exit()
        f = grab()
        if f is not None and is_battle(f):
            entered = True; break
        time.sleep(1.0)
    if not entered:
        print("no battle started in time -- stop", flush=True); break
    print("battle detected -- BOT PLAYING", flush=True)
    play_battle(g, inj, tpls, place_dt=1.0, collect=False)
    time.sleep(4.0)
g.close()
print("DONE", flush=True)
