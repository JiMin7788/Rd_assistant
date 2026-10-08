"""Offline dry-run of the gear bot on a recorded session: every STEP seconds read the
board, plan the next action, and print it beside the user's actual drags around
that moment. Nothing is injected.

  python tools/gear_replay.py <session_dir> [--step 2] [--t0 S] [--t1 S]
"""
import argparse, bisect, json, os, sys
import cv2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.board import COLS, ROWS
from rdom.perception.gear import read_board, ui_state
from rdom.policy.gear import evaluate, plan_next

ap = argparse.ArgumentParser()
ap.add_argument("session"); ap.add_argument("--step", type=float, default=2.0)
ap.add_argument("--t0", type=float, default=0); ap.add_argument("--t1", type=float, default=1e9)
a = ap.parse_args()

fr = [json.loads(l) for l in open(os.path.join(a.session, "frames.jsonl"))]
T0 = fr[0]["t"]; ts = [f["t"] for f in fr]
acts = [json.loads(l) for l in open(os.path.join(a.session, "events.jsonl"))]
acts = [e for e in acts if e["ev"] == "action"]


def cell_of(u, v):
    d, c = min((abs(u - cu) + 1.6 * abs(v - rv), ri * 5 + ci + 1)
               for ri, rv in enumerate(ROWS) for ci, cu in enumerate(COLS))
    return c if d < 0.07 else None


def user_moves(t, win):
    out = []
    for e in acts:
        dt = e["t"] - T0 - t
        if 0 <= dt < win:
            if e["kind"] == "drag":
                f, to = e["from"], e["to"]
                dst = "SUP" if to["v"] > 0.83 and to["u"] < 0.3 else cell_of(to["u"], to["v"])
                out.append(f"{cell_of(f['u'], f['v'])}->{dst}")
            else:
                out.append(f"tap({e['at']['u']:.2f},{e['at']['v']:.2f})")
    return out


caps = {}
transcended = False
t = a.t0
while t <= min(a.t1, ts[-1] - T0):
    i = bisect.bisect_left(ts, T0 + t); f = fr[min(i, len(fr) - 1)]
    cap = caps.get(f["seg"]) or caps.setdefault(
        f["seg"], cv2.VideoCapture(os.path.join(a.session, "video", f"seg_{f['seg']:05d}.mp4")))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f["si"]); ok, im = cap.read()
    if not ok:
        break
    rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    b = read_board(rgb); ui = ui_state(rgb)
    if any(d["variant"] in ("GearGrey", "GearRed", "GearBlue") for d in b):
        transcended = True
    ev = evaluate(b); act = plan_next(b, transcended=transcended, support_ready=True)
    row = " ".join(f"{d['type'][:2]}{d['pip']}" if d["type"] != "empty" else "..." for d in b)
    flags = "".join(k[0].upper() for k in ("transcend", "hunt", "hunt_popup", "power_panel") if ui[k])
    print(f"{t:6.1f} [{flags:3s}] {row} | G{ev['gears']} B{ev['bubbles']} clu{ev['largest_cluster']} "
          f"avg{ev['gear_avg']} {'DONE' if ev['complete'] else ''}\n"
          f"        bot: {act}   user: {' '.join(user_moves(t, a.step)) or '-'}", flush=True)
    t += a.step
