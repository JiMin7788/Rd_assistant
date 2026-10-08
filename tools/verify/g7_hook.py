"""G7 -- R4/R5 acceptance on real input: every click recorded, correctly typed.

Spec 03 §10 R4: 100 clicks, all recorded. R5: 50 taps + 50 drags classified
with 100% accuracy. The offline suite already proves the classifier; this
proves the hook actually delivers events and that hand-made gestures land on
the intended side of the threshold.

Enqueue-to-dequeue latency stands in for callback cost: if the callback were
doing real work the queue would fall behind, which is the failure that matters.

    python tools/verify/g7_hook.py --title "^LDPlayer" --taps 50 --drags 50
"""

from __future__ import annotations

import argparse
import queue
import statistics
import threading
import time

from rdom.recorder.events import PointerTracker
from rdom.recorder.geometry import Insets, Viewport
from rdom.recorder.hook import PointerHook
from rdom.recorder.window import WindowState, find_window, set_dpi_awareness


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="^LDPlayer")
    ap.add_argument("--sidebar", type=int, default=40)
    ap.add_argument("--tap-radius-n", type=float, default=0.012)
    ap.add_argument("--taps", type=int, default=50)
    ap.add_argument("--drags", type=int, default=50)
    args = ap.parse_args()

    set_dpi_awareness()
    hwnd = find_window(args.title)
    state = WindowState.read(hwnd)
    vp = Viewport(client=state.client, sidebar_right_px=args.sidebar, letterbox=Insets())

    actions: list = []
    lat: list[float] = []
    q: queue.Queue = queue.Queue()
    tracker = PointerTracker(
        viewport=vp,
        tap_radius_n=args.tap_radius_n,
        move_throttle_ms=8.0,
        on_raw=lambda p: None,
        on_action=actions.append,
    )

    stop = threading.Event()

    def process() -> None:
        while not stop.is_set():
            try:
                t, kind, sx, sy = q.get(timeout=0.2)
            except queue.Empty:
                continue
            lat.append((time.perf_counter() - t) * 1000.0)
            tracker.feed(t, kind, sx, sy)

    worker = threading.Thread(target=process, daemon=True)
    worker.start()

    hook = PointerHook(q)
    hook.start()

    total = args.taps + args.drags
    print(
        f"Inside the emulator window, make {args.taps} short TAPS, then\n"
        f"{args.drags} clear DRAGS (well over ~20px). Avoid the right sidebar.\n"
        "Press Enter here when done.\n"
    )
    try:
        input()
    except KeyboardInterrupt:
        pass

    hook.stop()
    time.sleep(0.3)
    stop.set()
    worker.join(2)
    tracker.close()

    n_tap = sum(1 for a in actions if a.kind == "tap")
    n_drag = sum(1 for a in actions if a.kind == "drag")

    print(f"actions recorded : {len(actions)}  (expected {total})")
    print(f"  taps  {n_tap}   (expected {args.taps})")
    print(f"  drags {n_drag}   (expected {args.drags})")
    print(f"orphan down={tracker.n_orphan_down}  up={tracker.n_orphan_up}  outside={tracker.n_outside}")
    if lat:
        print(
            f"queue latency ms: median={statistics.median(lat):.3f}  "
            f"p95={sorted(lat)[int(len(lat) * 0.95) - 1]:.3f}  max={max(lat):.3f}"
        )

    ok = (
        n_tap == args.taps
        and n_drag == args.drags
        and tracker.n_orphan_down == 0
        and tracker.n_orphan_up == 0
    )
    if not ok:
        print(
            "\nIf counts are close but not exact, the gestures were ambiguous rather\n"
            "than the hook being wrong -- redo it before changing tap_radius_n."
        )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
