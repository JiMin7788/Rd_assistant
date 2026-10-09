"""Keep the gear bot running without anyone watching.

Starts tools/gear_loop.py; if it crashes it is restarted (with a status message
and a screenshot to Discord). Five crashes within 30 minutes -> give up and
report, because something is systematically wrong (new screen, game update)
and blind restarts would only make it worse (user rule: anomaly -> stop, fix).
A normal exit (deadline reached) ends the supervisor too.

  python tools/supervisor.py [--until HH:MM]
Logs: data/bot_logs/YYYYMMDD_HHMM.log
"""
import argparse, collections, datetime, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.notify.discord import send_status

ap = argparse.ArgumentParser(); ap.add_argument("--until", default="23:59"); a = ap.parse_args()
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
LOGD = os.path.join(ROOT, "data", "bot_logs"); os.makedirs(LOGD, exist_ok=True)
crashes = collections.deque()
PID = os.path.join(ROOT, "data", "supervisor.pid")     # lets the Discord bot see whether we run
open(PID, "w").write(str(os.getpid()))
import atexit; atexit.register(lambda: os.path.exists(PID) and os.remove(PID))


def screenshot():
    try:
        from rdom.capture.live import LiveGrabber
        g = LiveGrabber(); f = g.grab(); g.close(); return f
    except Exception:
        return None


while True:
    log = os.path.join(LOGD, datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".log")
    with open(log, "w", encoding="utf-8") as fh:
        p = subprocess.run([PY, "-u", "-W", "ignore", os.path.join(ROOT, "tools", "gear_loop.py"), "--until", a.until],
                           cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    if p.returncode == 0:
        break                                         # deadline reached / clean stop
    tail = open(log, encoding="utf-8", errors="replace").read().strip().splitlines()[-6:]
    now = time.time(); crashes.append(now)
    while crashes and now - crashes[0] > 1800:
        crashes.popleft()
    if len(crashes) >= 5:
        send_status("⛔ 30분 안에 5번 오류 -- 봇 정지. 확인 필요\n```" + "\n".join(tail)[-1500:] + "```", screenshot())
        sys.exit(1)
    send_status(f"⚠ 봇 오류로 재시작 ({len(crashes)}/5)\n```" + "\n".join(tail)[-1200:] + "```", screenshot())
    time.sleep(10)
