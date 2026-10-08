"""G2b -- measure the emulator's window chrome so it can be pinned in config.

The tab bar and sidebar are dark but not black, so the letterbox scan cannot
find them. Left in the content area they make every ``(u, v)`` a coordinate in
the emulator window rather than in the game, which shifts and rescales the
whole session without ever looking broken.

Prints the colour profile near each edge, a suggestion, and writes a PNG with
the proposed crop drawn on it. Read the profile, confirm against the PNG, then
copy the numbers into ``[target.chrome]``.

    python tools/verify/g2b_chrome.py --title "^LDPlayer" --out chrome_check.png
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from rdom.recorder.geometry import Insets, Rect
from rdom.recorder.probe import profile_edges, suggest_chrome
from rdom.recorder.window import WindowState, find_window, monitor_info, set_dpi_awareness

SHOW = 56  # rows/cols printed at each edge


def grab(hwnd: int, client: Rect, monitor_index: int):
    import dxcam

    cam = dxcam.create(output_idx=monitor_index, output_color="RGB")
    if cam is None:
        raise SystemExit(f"dxcam: no output at index {monitor_index}")
    try:
        mon = monitor_info(hwnd)
        region = client.translated(-mon["rect"][0], -mon["rect"][1]).as_tuple()
        for _ in range(40):
            frame = cam.grab(region=region)
            if frame is not None:
                return frame
            time.sleep(0.05)
        raise SystemExit("dxcam returned no frame")
    finally:
        cam.release()


def dump(label: str, series, count: int, reverse: bool = False) -> None:
    n = len(series)
    print(f"\n-- {label} ({n} total)")
    idx = range(n - 1, n - 1 - count, -1) if reverse else range(min(count, n))
    for i in idx:
        print(f"   {i:5d}  {tuple(series[i])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="^LDPlayer")
    ap.add_argument("--monitor-index", type=int, default=0)
    ap.add_argument("--show", type=int, default=SHOW)
    ap.add_argument("--out", type=Path, default=Path("chrome_check.png"))
    args = ap.parse_args()

    set_dpi_awareness()
    hwnd = find_window(args.title)
    state = WindowState.read(hwnd)
    print(f"client {state.client.as_tuple()}  = {state.client.width}x{state.client.height}"
          f"  dpi={state.dpi:.2f}")

    frame = grab(hwnd, state.client, args.monitor_index)
    prof = profile_edges(frame, step=8)
    guess = suggest_chrome(prof)

    dump("top rows (index, mean RGB)", prof.rows, args.show)
    dump("bottom rows", prof.rows, args.show, reverse=True)
    dump("left cols", prof.cols, args.show)
    dump("right cols", prof.cols, args.show, reverse=True)

    print("\n" + "=" * 62)
    print("suggested [target.chrome]:")
    for k in ("left", "top", "right", "bottom"):
        note = "  <- no boundary found; read the profile above" if guess[k] == 0 else ""
        print(f"  {k:<6} = {guess[k]}{note}")

    content = Rect(
        guess["left"], guess["top"],
        state.client.width - guess["right"], state.client.height - guess["bottom"],
    )
    print(f"\ncontent would be {content.width}x{content.height}"
          f"  aspect {content.width / content.height:.4f}")
    print("Compare that aspect against `adb shell wm size`. A mismatch means the")
    print("emulator is stretching the android surface, which breaks any plan to")
    print("train on sprites extracted from the APK.")

    try:
        _write_png(frame, args.out, content)
        print(f"\nwrote {args.out} with the proposed crop outlined -- check that the")
        print("outline hugs the game and excludes every emulator pixel.")
    except Exception as exc:
        print(f"\n[warn] could not write {args.out}: {exc}", file=sys.stderr)
    return 0


def _write_png(frame, out: Path, content: Rect) -> None:
    """Outline the proposed crop and save, via ffmpeg (no imaging deps)."""
    h = len(frame)
    w = len(frame[0])
    raw = bytes(bytearray(int(c) for row in frame for px in row for c in px[:3]))
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-",
         "-vf", (f"drawbox=x={content.left}:y={content.top}"
                 f":w={content.width}:h={content.height}:color=lime@1.0:t=3"),
         "-frames:v", "1", str(out)],
        input=raw, check=True, capture_output=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
