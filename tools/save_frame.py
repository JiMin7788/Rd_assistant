"""Save one frame of the game window (only if nothing covers it).

    python tools/save_frame.py     -> data/support_frames/manual/<YYYYmmdd_HHMMSS>.png

Exit code 1 when not saved. Reads the screen only; never injects input.
"""
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


def main():
    grabber = LiveGrabber()
    try:
        frame = grabber.grab()
        covered = not grabber.unobscured()
    finally:
        grabber.close()
    # AI-NOTE: the covered check runs before any name is claimed, so a covered window leaves no file.
    if covered:
        print("not saved: game window covered")
        return 1
    ok, buf = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    if not ok:
        print("not saved: game window covered")
        return 1
    claimed = claim_file(ROOT / "data" / "support_frames" / "manual", time.strftime("%Y%m%d_%H%M%S"))
    if claimed is None:
        print("not saved: no free file name")
        return 1
    saved, f = claimed
    with f:
        f.write(buf.tobytes())
    print(f"saved {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
