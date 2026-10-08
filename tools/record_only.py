"""Record-only observer — the USER plays, we only watch and save data.

Passive by construction: it NEVER creates an Injector, so it cannot tap, swipe or
touch the game in any way (user request 2026-09-17 — "플레이는 내가 할거고 너는 기록만 해").
It waits for a battle, then every INTERVAL seconds saves the 15 cell crops as training
data (confident colour-rule label, ambiguous -> _unlabeled, near-duplicate deduped) and
logs the belief board. Repeats for every battle you play until you stop the task or
move the window.

  --frames   also save the full frame each tick into data/sessions/<ts>/ (enables the
             docs/07 Layer B temporal label-propagation later). Off by default (disk).
  --interval SECONDS   capture cadence (default 0.7).
"""
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rdom.capture.live import LiveGrabber
from rdom.perception.board import read_board, load_templates, is_battle, is_game_over
from rdom.perception.tracker import CellTracker
from tools.bot_live import _collect_crops, progress_str

ap = argparse.ArgumentParser()
ap.add_argument("--frames", action="store_true", help="also save full frames for Layer B")
ap.add_argument("--interval", type=float, default=0.7)
args = ap.parse_args()

g = LiveGrabber()
tpls = load_templates()
seen = set()
battle = 0
SESS_ROOT = r"C:\dev\rdom\data\sessions"


def moved():
    """window_moved(), but tolerant: an invalid/closed window handle (WinError 1400,
    e.g. LDPlayer minimised or closed between battles) is NOT treated as 'moved' -- we
    just keep waiting instead of crashing the recorder."""
    try:
        return g.window_moved()
    except OSError:
        return False


def grab():
    try:
        return g.grab()
    except Exception:
        return None

print("record-only: PASSIVE (no taps). Start a battle whenever you like; "
      "stop this task to end.", flush=True)
try:
    while True:
        if moved():
            print("window moved -- stop", flush=True); break
        f0 = grab()
        if f0 is None or not is_battle(f0):    # no frame / not in battle -> keep waiting
            time.sleep(1.0); continue

        battle += 1
        tr = CellTracker()
        n = 0
        frames_dir = None
        if args.frames:
            frames_dir = os.path.join(SESS_ROOT, time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(frames_dir, exist_ok=True)
        print(f"=== battle {battle} detected -- recording (you play) ==="
              + (f" frames->{frames_dir}" if frames_dir else ""), flush=True)

        while True:
            if moved():
                print("window moved -- stop", flush=True); g.close(); sys.exit()
            frame = grab()
            if frame is None:                  # transient capture failure -> retry
                time.sleep(0.5); continue
            if is_game_over(frame):
                print(f"battle {battle} over -- {n} ticks, crops~{len(seen)}", flush=True)
                break
            if not is_battle(frame):          # popup/dialog: still passive, just wait
                time.sleep(0.5); continue
            _collect_crops(frame, seen)       # save training crops (deduped)
            if frames_dir is not None:
                from PIL import Image
                Image.fromarray(frame).save(
                    os.path.join(frames_dir, f"{n:05d}_{int(time.time()*1000)}.png"))
            tr.update(read_board(frame, tpls))
            n += 1
            if n % 15 == 0:
                print(f"  [{battle}] {progress_str(tr.belief_board())}  "
                      f"uncertain={len(tr.uncertain())}  crops~{len(seen)}", flush=True)
            time.sleep(args.interval)
        time.sleep(3.0)
except KeyboardInterrupt:
    pass
g.close()
print(f"DONE recording -- {battle} battles, {len(seen)} crops", flush=True)
