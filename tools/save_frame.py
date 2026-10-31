"""Save one frame of the game window (only if nothing covers it).

    python tools/save_frame.py     -> data/support_frames/manual/<YYYYmmdd_HHMMSS>.png

    python tools/save_frame.py --profile ld --every 5 --minutes 20
        -> data/support_frames/manual/ld_<YYYYmmdd_HHMMSS>/<stamp>.png every 5 s for 20 min

--profile picks the window (gpg = config/recorder.toml, ld = config/recorder_ld.toml).
Exit code 1 when nothing was saved. Reads the screen only; never injects input.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdom.capture.live import LiveGrabber  # noqa: E402

MAX_SUFFIX = 99


def claim_file(folder, stamp):
    """Create `<stamp>.png`, else `<stamp>_2.png` ... `_99.png`, by exclusive create ('xb').
    Returns (path, open binary file) or None when every name is taken."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_SUFFIX + 1):
        path = folder / (f"{stamp}.png" if n == 1 else f"{stamp}_{n}.png")
        try:
            # AI-NOTE: 'xb' makes the claim atomic, so a frame saved in the same second (or by
            # another process) is never overwritten.
            return path, open(path, "xb")
        except FileExistsError:
            continue
    return None


PROFILES = {"gpg": "config/recorder.toml", "ld": "config/recorder_ld.toml"}
MANUAL = ROOT / "data" / "support_frames" / "manual"


def save_one(grabber, folder):
    """Grab one frame and save it under `folder`. Returns the path, or None (and
    prints why) when the window is covered or no name is free."""
    frame = grabber.grab()
    # AI-NOTE: the covered check runs before any name is claimed, so a covered window leaves no file.
    if not grabber.unobscured():
        print("not saved: game window covered")
        return None
    ok, buf = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    if not ok:
        print("not saved: game window covered")
        return None
    claimed = claim_file(folder, time.strftime("%Y%m%d_%H%M%S"))
    if claimed is None:
        print("not saved: no free file name")
        return None
    saved, f = claimed
    with f:
        f.write(buf.tobytes())
    print(f"saved {saved}")
    return saved


def run_every(grabber, folder, every, minutes, sleep=time.sleep, clock=time.monotonic):
    """Save a frame every `every` seconds for `minutes`. Returns how many were saved."""
    end = clock() + minutes * 60
    n = 0
    while True:
        if save_one(grabber, folder) is not None:
            n += 1
        if clock() + every > end:
            return n
        sleep(every)


def main(argv=None, grabber_factory=LiveGrabber):
    ap = argparse.ArgumentParser(description="Save a frame of the game window (never injects input).")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="gpg",
                    help="ld = LDPlayer window, gpg = Google Play Games (default)")
    ap.add_argument("--every", type=float, default=None, metavar="SEC",
                    help="keep saving a frame every SEC seconds (needs --minutes)")
    ap.add_argument("--minutes", type=float, default=None, help="how long --every runs")
    a = ap.parse_args(argv)
    if (a.every is None) != (a.minutes is None) or (a.every is not None and a.every <= 0):
        ap.error("--every SEC and --minutes MIN go together (SEC > 0)")
    grabber = grabber_factory(config=PROFILES[a.profile])
    try:
        if a.every is None:
            return 0 if save_one(grabber, MANUAL) else 1
        folder = MANUAL / f"{a.profile}_{time.strftime('%Y%m%d_%H%M%S')}"
        n = run_every(grabber, folder, a.every, a.minutes)
    finally:
        grabber.close()
    print(f"saved {n} frames into {folder}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
