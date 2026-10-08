"""Wait for the user to start a battle, then play it while collecting training
crops. Repeats for several battles (user starts each). Works around flaky coop
auto-start: the human does the matchmaking, the bot plays + gathers diverse data."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rdom.capture.live import LiveGrabber
from rdom.perception.board import is_battle, is_game_over, load_templates
from rdom.input.inject import Injector
from tools.bot_live import play_battle, exit_to_lobby

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
g = LiveGrabber(); inj = Injector(execute=True); tpls = load_templates()
for r in range(rounds):
    print(f"=== waiting for battle {r+1}/{rounds} (start 협동 in the game) ===", flush=True)
    entered = False
    for _ in range(180):                 # up to ~3 min for the human to start it
        if g.window_moved():
            print("window moved -- stop", flush=True); g.close(); sys.exit()
        if is_battle(g.grab()):
            entered = True; break
        time.sleep(1.0)
    if not entered:
        print("no battle started in time -- stop", flush=True); break
    print("battle detected -- play + collect", flush=True)
    play_battle(g, inj, tpls, place_dt=1.0, collect=True)
    time.sleep(4.0)
g.close()
print("DONE collecting", flush=True)
