"""Save one frame of the game window (only if nothing covers it).

    python tools/save_frame.py     -> data/support_frames/manual/<YYYYmmdd_HHMMSS>.png

Exit code 1 when not saved. Reads the screen only; never injects input.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdom.capture.live import LiveGrabber  # noqa: E402
from rdom.perception.collect import save_frame  # noqa: E402


def main():
    grabber = LiveGrabber()
    try:
        frame = grabber.grab()
        path = ROOT / "data" / "support_frames" / "manual" / (time.strftime("%Y%m%d_%H%M%S") + ".png")
        saved = save_frame(frame, path, grabber.unobscured())
    finally:
        grabber.close()
    if saved is None:
        print("not saved: game window covered")
        return 1
    print(f"saved {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
