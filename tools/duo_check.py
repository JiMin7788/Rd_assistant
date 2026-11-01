"""No-input check of both game windows (LD + GPG) before the first duo run.

    python tools/duo_check.py

Runs the start check for 'ld' and 'gpg' (places the windows), then starts two child processes at
the same time that each grab ONE frame of one window and print its shape, to prove two dxcam
duplications of the same output work in two processes. It never injects input and never saves
frames. Prints only 'start check: OK|FAIL ...' lines; exit 0 only when every line is OK.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdom import profile  # noqa: E402
from rdom.capture import preflight  # noqa: E402

NAMES = ["ld", "gpg"]


def _spawn(name):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--grab", name],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def _result(name, proc):
    out, _ = proc.communicate()
    line = (out or "").strip().splitlines()
    if proc.returncode == 0 and line:
        return name, True, f"{name} 프레임 {line[-1]}"
    return name, False, f"{name} 프레임을 못 읽었어요"


def _grab_one(name):
    from rdom.capture.live import LiveGrabber
    g = LiveGrabber(str(ROOT / profile.get(name).config))
    try:
        print(g.grab().shape)
    finally:
        g.close()


def main(argv=None, *, check_fn=None, spawn=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--grab", choices=NAMES, help=argparse.SUPPRESS)   # child mode
    args = ap.parse_args(argv)
    if args.grab:
        _grab_one(args.grab)
        return 0
    results = (check_fn or preflight.check)(NAMES, place=True)
    if all(ok for _, ok, _ in results):
        spawn = spawn or _spawn
        # AI-NOTE: both children are started before either is waited on, so the two
        # dxcam duplications really run at the same time.
        procs = [(n, spawn(n)) for n in NAMES]
        results += [_result(n, p) for n, p in procs]
    for line in preflight.format_lines(results):
        print(line)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
