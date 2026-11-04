"""One console for everything: the Discord bot + the game-bot supervisor (both game bots).

  python tools/run_all.py [--no-game] [--gear-only]

- Discord bot: always running; restarted 10 s after it dies.
- Supervisor (game loops): started now unless --no-game, or later with Discord /시작.
  Default = duo (two gear bots, one per Google Play Games window); --gear-only starts
  the first gear bot alone (public room).
  All children share THIS console's window but write their output to files
  (data/discord_bot.log, data/bot_logs/*) -- no extra windows. This console shows
  the important lines of the logs, tagged [기어1] / [기어2] / [디코].
- Closing this window (or Ctrl+C) stops everything.
"""
import argparse, fnmatch, glob, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
DATA = os.path.join(ROOT, "data")
PID = os.path.join(DATA, "supervisor.pid")
LOCK = os.path.join(DATA, "run_all.pid")
SECOND_COPY_WAIT_S = 5        # leave the refusal text readable before the console closes
SHOW = ("===", "room code", "someone joined", "battle result", "game over", "로비로",
        "게임이 꺼져", "팝업", "modal", "unknown screen", "!!", "Traceback", "Error",
        "stopping", "loop done", "초월", "discord bot ready", "tick:", "dm failed",
        "milestone", "deck route", "support deck", "frame not saved", "power panel", "power card",
        "unreadable", "board changed without our action",
        "power-up", "Lv check", "look-alike", "game-over screen", "support result",
        "battle still on screen",
        "invite", "초대", "start check", "시작 점검", "wrong deck", "restart")


def supervisor_args(gear_only):
    # AI-NOTE: supervisor.py defaults to duo too, but the mode is always passed explicitly.
    return ["--mode", "gear" if gear_only else "duo"]


def header_text(gear_only, host="대변먹는자", partner="배속봇"):
    if gear_only:
        return "기어봇만 시작 (구글)"
    return f"두 봇 시작 (기어1=구글 {host} · 기어2=구글 {partner})"


def load_names(root=ROOT):
    """(host, partner) from config/duo.toml; defaults when the file or a key is missing."""
    try:
        import tomllib
        with open(os.path.join(root, "config", "duo.toml"), "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        cfg = {}
    return cfg.get("host", "대변먹는자"), cfg.get("partner", "배속봇")


def tail_specs(data_dir=DATA):
    """(glob pattern, console tag) per followed log. One Tail per bot, so each bot's newest log is followed."""
    logs = os.path.join(data_dir, "bot_logs")
    # logs are named by profile (supervisor._log_path); a same-minute restart is YYYYMMDD_HHMM_gpg_2.log.
    # AI-NOTE: "gpg[_.]*" does not match gpg2 files, "gpg2*" matches only those.
    return [(os.path.join(logs, "2*_gpg[_.]*"), "기어1"),
            (os.path.join(logs, "2*_gpg2*"), "기어2"),
            (os.path.join(data_dir, "discord_bot.log"), "디코")]


def tag_for(filename):
    """Console tag for a log file name, or None when it is not followed."""
    name = os.path.basename(filename)
    for pattern, tag in tail_specs(""):
        if fnmatch.fnmatch(name, os.path.basename(pattern)):
            return tag
    return None


def shown(line):
    return any(k in line for k in SHOW)


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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-game", action="store_true")
    ap.add_argument("--gear-only", action="store_true")
    a = ap.parse_args(argv)

    if (p := read_pid(LOCK)) and alive(p) and p != os.getpid():
        print(f"이미 실행 중이에요 -- 두 번째 실행은 무시합니다 (pid {p}). 이 창은 닫아도 됩니다.")
        time.sleep(SECOND_COPY_WAIT_S); return 1       # non-zero: nothing was started
    open(LOCK, "w").write(str(os.getpid()))

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
            start("supervisor.py", *supervisor_args(a.gear_only), log=os.path.join(DATA, "bot_logs", "supervisor.log"))
            print(header_text(a.gear_only, *load_names()))

    tails = [(tag, Tail(pattern)) for pattern, tag in tail_specs()]
    try:
        while True:
            for tag, t in tails:
                for l in t.lines():
                    if shown(l):
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
