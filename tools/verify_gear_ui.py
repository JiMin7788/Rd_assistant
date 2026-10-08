"""Run perception.gear.ui_scores over the 2026-10-07 recording (every 0.5 s) and
dump the score timeline, to set/check the button thresholds against the user's taps."""
import json, sys, os, cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.gear import ui_scores
S = r"C:\dev\rdom\data\sessions\2026-10-07_1820_28fb"; t0 = 13375.932882
fr = [json.loads(l) for l in open(S + r"\frames.jsonl")]
rows = []
for seg in sorted({f["seg"] for f in fr}):
    cap = cv2.VideoCapture(S + rf"\video\seg_{seg:05d}.mp4")
    for f in (f for f in fr if f["seg"] == seg):
        ok, im = cap.read()
        if not ok: break
        if f["i"] % 15: continue
        s = ui_scores(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
        rows.append([f["t"] - t0] + [s[k] for k in ("transcend", "hunt", "hunt_popup_btn", "power_gear_card")])
np.save(r"C:\dev\rdom\_gear\ui_timeline.npy", np.array(rows))
print(len(rows))
