"""One console for everything: the Discord bot + the game-bot supervisor.

  python tools/run_all.py [--until HH:MM] [--no-game]

- Discord bot: always running; restarted 10 s after it dies.
- Supervisor (game loop): started now unless --no-game, or later with Discord /시작.
  Both children share THIS console's window but write their output to files
  (data/discord_bot.log, data/bot_logs/*) -- no extra windows. This console shows
  the important lines of both logs.
- Closing this window (or Ctrl+C) stops everything.
"""
import argparse, glob, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
DATA = os.path.join(ROOT, "data")
PID = os.path.join(DATA, "supervisor.pid")
LOCK = os.path.join(DATA, "run_all.pid")
SHOW = ("===", "room code", "someone joined", "battle result", "game over", "로비로",
        "게임이 꺼져", "팝업", "modal", "unknown screen", "!!", "Traceback", "Error",
        "stopping", "loop done", "초월", "discord bot ready", "tick:", "dm failed")

ap = argparse.ArgumentParser()
ap.add_argument("--until", default="23:59")
ap.add_argument("--no-game", action="store_true")
a = ap.parse_args()


def alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
    except Exception:
        return False


def read_pid(path):
    try:
        return int(open(path).read())
    except Exception:
        return None


if (p := read_pid(LOCK)) and alive(p) and p != os.getpid():
    print(f"이미 실행 중입니다 (pid {p}). 이 창은 닫아도 됩니다."); time.sleep(5); sys.exit(0)
open(LOCK, "w").write(str(os.getpid()))


def start(script, *args, log):
    fh = open(log, "a", encoding="utf-8")
    return subprocess.Popen([PY, "-u", "-W", "ignore", os.path.join(ROOT, "tools", script), *args],
                            cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


class Tail:
    """Follow the newest file matching a pattern, yielding new lines."""
    def __init__(self, pattern):
        self.pattern, self.path, self.pos = pattern, None, 0

    def lines(self):
        files = sorted(glob.glob(self.pattern), key=os.path.getmtime)
        if not files:
            return []
        if files[-1] != self.path:
            self.path = files[-1]
            self.pos = 0 if self.path and time.time() - os.path.getctime(self.path) < 30 else os.path.getsize(self.path)
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                f.seek(self.pos); out = f.read(); self.pos = f.tell()
        except OSError:
            return []
        return out.splitlines()


os.system("title rdom 봇 (이 창을 닫으면 전부 종료)")
print(f"랜다2 봇 통합 실행 -- 이 창 하나만 띄워 두세요. 닫으면 게임봇·디스코드봇 모두 종료.\n")
disc = start("discord_bot.py", log=os.path.join(DATA, "discord_bot.console.log"))
if not a.no_game:
    if (p := read_pid(PID)) and alive(p):
        print("게임봇은 이미 실행 중 -- 그대로 둡니다")
    else:
        for f in ("PAUSE", "STOP"):
            if os.path.exists(os.path.join(DATA, f)):
                os.remove(os.path.join(DATA, f))
        start("supervisor.py", "--until", a.until, log=os.path.join(DATA, "bot_logs", "supervisor.log"))
        print(f"게임봇 시작 (종료 {a.until})")

game, dlog = Tail(os.path.join(DATA, "bot_logs", "2*.log")), Tail(os.path.join(DATA, "discord_bot.log"))
try:
    while True:
        for tag, t in (("게임", game), ("디코", dlog)):
            for l in t.lines():
                if any(k in l for k in SHOW):
                    print(f"{time.strftime('%H:%M:%S')} [{tag}] {l}", flush=True)
        if disc.poll() is not None:
            print(f"{time.strftime('%H:%M:%S')} [디코] 디스코드 봇 종료됨 (code {disc.returncode}) -- 10초 후 재시작", flush=True)
            time.sleep(10)
            disc = start("discord_bot.py", log=os.path.join(DATA, "discord_bot.console.log"))
        time.sleep(1.0)
except KeyboardInterrupt:
    pass
finally:
    disc.terminate()
    if os.path.exists(LOCK):
        os.remove(LOCK)
