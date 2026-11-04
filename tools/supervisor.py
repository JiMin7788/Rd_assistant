"""Keep the bots running without anyone watching (rdF04: one supervisor, two children).

  python tools/supervisor.py [--mode duo|gear]

duo (default): tools/gear_loop.py --profile gpg --role inviter ([기어1]) and --profile gpg2 --role joiner
([기어2]): two gear bots, one per Google Play Games window. gear: only the gpg bot, --role public.

Child exit codes (tools/gear_loop.py): 0 = clean stop, 3 = guard stop, anything else = crash.
A crash is restarted after 10 s with a status message and a screenshot of that bot's window. The 5th crash
of one bot within 30 minutes, or a guard stop of either bot, stops both: data/STOP is written (the other bot
finishes its current game and exits), nothing is restarted, the supervisor waits for all children and exits 1.
When every child exited 0 the supervisor exits 0. The user rule is: anomaly -> stop and fix, never blind restarts.
Logs: data/bot_logs/YYYYMMDD_HHMM_<profile>.log (a new file per start; named by profile because both duo bots are "gear").
"""
import argparse, collections, datetime, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
GEAR_LOOP = os.path.join(ROOT, "tools", "gear_loop.py")
CRASH_WINDOW_S = 1800
CRASH_LIMIT = 5
RESTART_DELAY_S = 10
POLL_S = 1

# (bot, profile, role) per mode; tag and config come from rdom.profile
CHILDREN = {
    "duo": (("gear", "gpg", "inviter"), ("gear", "gpg2", "joiner")),
    "gear": (("gear", "gpg", "public"),),
}

EXIT_CLEAN, EXIT_GUARD = 0, 3                      # same contract as tools/gear_loop.py

RESTART_TEXT = "⚠ {tag} 봇 오류로 재시작 ({n}/5)"
LIMIT_TEXT_DUO = "⛔ {tag} 30분 안에 5번 오류 -- 두 봇 모두 정지 (다른 봇은 지금 판을 끝내고 멈춰요). 확인 필요"
LIMIT_TEXT_GEAR = "⛔ [기어1] 30분 안에 5번 오류 -- 봇 정지. 확인 필요"
GUARD_TEXT = "⛔ {tag} 봇이 멈춰서 두 봇 모두 정지 (다른 봇은 지금 판을 끝내고 멈춰요)"
ENDED_TEXT = "■ 두 봇 모두 정지됨"


def popen_spawn(cmd, log_path):
    """Start a real child with stdout/stderr in log_path."""
    with open(log_path, "w", encoding="utf-8") as fh:
        return subprocess.Popen(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


def grab_screenshot(profile):
    """One frame of that profile's window, or None (failures give no image)."""
    try:
        from rdom.capture.live import LiveGrabber
        g = LiveGrabber(config=os.path.join(ROOT, profile.config))
        try:
            return g.grab()
        finally:
            g.close()
    except Exception:
        return None


class _Bot:
    def __init__(self, name, profile, role):
        self.name, self.profile, self.role = name, profile, role
        self.proc = None
        self.restart_at = None
        self.crashes = collections.deque()
        self.log = None


class Supervisor:
    def __init__(self, mode, data_dir, spawn=popen_spawn, clock=time.time, sleep=time.sleep,
                 notify=None, screenshot=grab_screenshot, py=PY, script=GEAR_LOOP):
        from rdom import profile as profiles
        self.mode, self.data = mode, data_dir
        self.spawn, self.clock, self.sleep = spawn, clock, sleep
        self.notify, self.screenshot = notify, screenshot
        self.py, self.script = py, script
        self.bots = [_Bot(b, profiles.get(p), r) for b, p, r in CHILDREN[mode]]
        self.stopping = False
        self.pid_path = os.path.join(data_dir, "supervisor.pid")
        self.mode_path = os.path.join(data_dir, "bot_mode.json")
        self.stop_path = os.path.join(data_dir, "STOP")
        self.log_dir = os.path.join(data_dir, "bot_logs")

    # --- helpers
    def _say(self, text, frame=None):
        if self.notify is None:
            from rdom.notify.discord import send_status
            self.notify = send_status
        try:
            self.notify(text, frame)
        except Exception as e:                      # a Discord outage must not stop the supervision
            print("notify failed:", e, flush=True)

    def _log_path(self, bot):
        stamp = datetime.datetime.fromtimestamp(self.clock()).strftime("%Y%m%d_%H%M")
        # AI-NOTE: rdT06: both duo bots are "gear", so the log is named by profile (gpg / gpg2), not by bot.
        path = os.path.join(self.log_dir, f"{stamp}_{bot.profile.name}.log")
        n = 1
        # AI-NOTE: a restart inside the same minute must not overwrite the log of the crash just reported.
        while os.path.exists(path):
            n += 1
            path = os.path.join(self.log_dir, f"{stamp}_{bot.profile.name}_{n}.log")
        return path

    def _tail(self, bot):
        try:
            with open(bot.log, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().strip().splitlines()[-6:]
        except OSError:
            lines = []
        return "```" + "\n".join(lines)[-1200:] + "```"

    def _write_mode(self):
        doc = {"mode": self.mode, "t": self.clock(),
               "bots": [{"bot": b.name, "tag": b.profile.tag, "profile": b.profile.name,
                         "pid": getattr(b.proc, "pid", None)} for b in self.bots]}
        tmp = self.mode_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, self.mode_path)

    def _start(self, bot):
        bot.log = self._log_path(bot)
        cmd = [self.py, "-u", "-W", "ignore", self.script,
               "--profile", bot.profile.name, "--role", bot.role, "--execute"]
        bot.proc = self.spawn(cmd, bot.log)
        bot.restart_at = None
        self._write_mode()

    def _stop_both(self):
        """STOP for the other bot (it finishes its game); no restarts from here on."""
        self.stopping = True
        with open(self.stop_path, "w") as fh:
            fh.write("supervisor")
        for b in self.bots:
            b.restart_at = None

    # --- events
    def _exited(self, bot, rc):
        bot.proc = None
        if rc == EXIT_CLEAN or self.stopping:       # already stopping: just wait for the rest
            return
        if rc == EXIT_GUARD:
            self._stop_both()
            # AI-NOTE: gear mode has no "other bot"; the child already reported its own guard stop.
            if self.mode == "duo":
                self._say(GUARD_TEXT.format(tag=bot.profile.tag))
            return
        now = self.clock()
        bot.crashes.append(now)
        while bot.crashes and now - bot.crashes[0] > CRASH_WINDOW_S:
            bot.crashes.popleft()
        n = len(bot.crashes)
        if n >= CRASH_LIMIT:
            self._stop_both()
            text = LIMIT_TEXT_DUO.format(tag=bot.profile.tag) if self.mode == "duo" else LIMIT_TEXT_GEAR
            self._say(text + "\n" + self._tail(bot), self.screenshot(bot.profile))
            return
        self._say(RESTART_TEXT.format(tag=bot.profile.tag, n=n) + "\n" + self._tail(bot),
                  self.screenshot(bot.profile))
        bot.restart_at = now + RESTART_DELAY_S

    def run(self):
        os.makedirs(self.log_dir, exist_ok=True)
        try:
            with open(self.pid_path, "w") as fh:    # lets the Discord bot see whether we run
                fh.write(str(os.getpid()))
            self._write_mode()
            if self.mode == "duo":
                from rdom.notify.room_state import write_room
                write_room(None, "duo")
            for b in self.bots:
                self._start(b)
            while any(b.proc is not None or b.restart_at is not None for b in self.bots):
                for b in self.bots:
                    if b.proc is not None:
                        rc = b.proc.poll()
                        if rc is not None:
                            self._exited(b, rc)
                    elif b.restart_at is not None and self.clock() >= b.restart_at:
                        self._start(b)
                self.sleep(POLL_S)
            if self.stopping:
                if self.mode == "duo":
                    self._say(ENDED_TEXT)
                return 1
            return 0
        finally:
            for p in (self.pid_path, self.mode_path, self.stop_path):
                try:
                    os.remove(p)
                except OSError:
                    pass


def running_supervisor(pid_path):
    """pid of ANOTHER live python process named in `pid_path`, else None (missing/stale file).
    AI-NOTE: 2026-11-05 two full stacks ran at once and every window got two bots; run_all and the
    Discord /시작 both start supervisors, so the supervisor itself must refuse a second copy."""
    try:
        import psutil
        pid = int(open(pid_path).read())
        if pid != os.getpid() and psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower():
            return pid
    except Exception:
        pass
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=sorted(CHILDREN), default="duo")
    a = ap.parse_args(argv)
    data = os.path.join(ROOT, "data")
    other = running_supervisor(os.path.join(data, "supervisor.pid"))
    if other:
        print(f"이미 실행 중이에요 -- 두 번째 실행은 무시합니다 (pid {other})", flush=True)
        return 2                                   # non-zero, no bot was started
    return Supervisor(a.mode, data).run()


if __name__ == "__main__":
    sys.exit(main())
