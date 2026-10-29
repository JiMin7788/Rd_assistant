"""Check the support-deck perception assets against the saved H1 data.

  python tools/check_support_assets.py [--data-dir <repo>/data]

Prints one line per check; exit 0 (exit 1 only on an exception). Missing inputs give n=0 / 0/0.
  score: n=<n> correct=<c> none=<k> wrong=<w>   read_score on data/digits/score/<value>_<any>.png crops
  score lobby: none=<k>/<n>                      read_score is None on data/support_frames/manual lobby frames

Run on C:/dev/rdom/data (2026-10-29):
  score: n=42 correct=38 none=4 wrong=0
  score lobby: none=1/1
"""
import argparse, glob, os, sys
import cv2

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.perception import board, score


def check_score(data_dir):
    """Crops are cut with SCORE_BOX, so the frame fed to read_score is the crop itself laid out at its box position."""
    n = correct = none = wrong = 0
    for p in sorted(glob.glob(os.path.join(data_dir, "digits", "score", "*.png"))):
        value = os.path.basename(p).split("_", 1)[0]
        img = cv2.imread(p)
        if img is None or not value.isdigit():            # 0-byte / corrupt file or no value prefix
            continue
        n += 1
        r = score.read_score(_frame_for_crop(img))
        if r is None:
            none += 1
        elif r == int(value):
            correct += 1
        else:
            wrong += 1
    return f"score: n={n} correct={correct} none={none} wrong={wrong}"


def _frame_for_crop(crop_bgr):
    """Blank RGB frame (9:16, 2224 high like the H1 frames) with the crop pasted at SCORE_BOX, so read_score cuts it back out."""
    import numpy as np
    h = 2224; W = round(h * 9 / 16)
    u0, v0, u1, v1 = score.SCORE_BOX
    x0, y0, x1, y1 = int(u0 * W), int(v0 * h), int(u1 * W), int(v1 * h)
    f = np.zeros((h, W, 3), np.uint8)
    f[y0:y1, x0:x1] = cv2.resize(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB), (x1 - x0, y1 - y0))
    return f


def check_score_lobby(data_dir):
    n = none = 0
    for p in sorted(glob.glob(os.path.join(data_dir, "support_frames", "manual", "*.png"))):
        bgr = cv2.imread(p)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if board.is_battle(rgb):
            continue
        n += 1
        if score.read_score(rgb) is None:
            none += 1
    return f"score lobby: none={none}/{n}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    a = ap.parse_args(argv)
    try:
        print(check_score(a.data_dir))
        print(check_score_lobby(a.data_dir))
    except Exception as e:                                # AI-NOTE: only an exception is a failure; bad reads are reported in the lines
        print(f"error: {e!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
