"""G5 -- R2 acceptance: dxcam sustains the target rate on this machine.

Spec 03 §10 R2: over 60 seconds, dup ratio < 2% and effective FPS >= 29.5.

Frames are discarded as they arrive -- this measures the capture path alone,
with no encoder in the way, so a failure here is dxcam or the emulator's own
frame rate rather than ffmpeg.

    python tools/verify/g5_capture.py --title "^LDPlayer" --seconds 60
"""

from __future__ import annotations

import argparse
import queue
import threading
import time

from rdom.recorder.capture import CaptureLoop
from rdom.recorder.window import WindowState, find_window, monitor_info, set_dpi_awareness


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="^LDPlayer")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--monitor-index", type=int, default=0)
    ap.add_argument("--max-dup-ratio", type=float, default=0.02)
    ap.add_argument("--min-fps", type=float, default=29.5)
    args = ap.parse_args()

    set_dpi_awareness()
    hwnd = find_window(args.title)
    state = WindowState.read(hwnd)
    mon = monitor_info(hwnd)
    region = state.client.translated(-mon["rect"][0], -mon["rect"][1])

    print(f"client={state.client.as_tuple()}  monitor={mon['rect']}  region={region.as_tuple()}")
    print(f"capturing {args.seconds:.0f}s at {args.fps} fps -- keep the game running and visible")

    warns: list[tuple[str, dict]] = []
    q: queue.Queue = queue.Queue(maxsize=120)
    stop = threading.Event()

    def drain() -> None:
        while not stop.is_set():
            try:
                q.get(timeout=0.2)
            except queue.Empty:
                pass

    drainer = threading.Thread(target=drain, daemon=True)
    drainer.start()

    cap = CaptureLoop(
        region=region,
        target_fps=args.fps,
        out_q=q,
        on_warn=lambda c, d: warns.append((c, d)),
        monitor_index=args.monitor_index,
    )
    t0 = time.perf_counter()
    cap.start()
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    cap.stop()
    elapsed = time.perf_counter() - t0
    stop.set()
    drainer.join(2)

    eff_fps = cap.n_grabbed / elapsed if elapsed else 0.0
    dup_ratio = cap.n_dup / cap.n_grabbed if cap.n_grabbed else 1.0

    print(f"\nelapsed={elapsed:.1f}s  grabbed={cap.n_grabbed}  dup={cap.n_dup}  stalls={cap.n_stalled}")
    print(f"effective fps = {eff_fps:.2f}  (min {args.min_fps})")
    print(f"dup ratio     = {dup_ratio:.4f}  (max {args.max_dup_ratio})")
    if warns:
        print(f"warnings: {warns[:5]}{' ...' if len(warns) > 5 else ''}")

    ok = eff_fps >= args.min_fps and dup_ratio < args.max_dup_ratio and cap.n_stalled == 0
    if cap.n_stalled:
        print("NOTE: stalls here mean the drain thread could not keep up, which is")
        print("      not the real pipeline -- but investigate before a long session.")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
