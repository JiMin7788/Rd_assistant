"""G3 -- R1 acceptance: (u,v) reproducibility across window moves.

Spec 03 §10 R1: move the window 10 times, hover the SAME in-game element each
time, and the normalized coordinate must reproduce within 0.002.

This is what makes a moved window safe to treat as fatal rather than something
to silently correct: if the transform tracks the move exactly, there is no
ambiguity left to paper over.

Run it once per Windows display-scaling setting (100 / 125 / 150%) -- the same
script doubles as the DPI check, since it prints the scale it saw.

    python tools/verify/g3_repro.py --title "^LDPlayer" --rounds 10
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes

from rdom.recorder.geometry import Insets, Viewport
from rdom.recorder.window import WindowState, find_window, set_dpi_awareness

TOLERANCE = 0.002


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="^LDPlayer")
    ap.add_argument("--sidebar", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=10)
    args = ap.parse_args()

    set_dpi_awareness()
    hwnd = find_window(args.title)

    print(
        "Pick one small, fixed UI element in the game (a corner icon works).\n"
        "Each round: MOVE the emulator window somewhere new, hover that exact\n"
        "element, then press Enter without moving the mouse.\n"
    )

    samples: list[tuple[float, float, tuple[int, int, int, int], float]] = []
    for r in range(args.rounds):
        input(f"  round {r + 1}/{args.rounds} -- hover the element, then Enter: ")
        state = WindowState.read(hwnd)
        if state.minimized:
            print("  window is minimized; skipping round")
            continue
        vp = Viewport(
            client=state.client, sidebar_right_px=args.sidebar, letterbox=Insets()
        )
        sx, sy = cursor_pos()
        if not vp.contains(sx, sy):
            print(f"  cursor {(sx, sy)} is outside the content area; round ignored")
            continue
        u, v = vp.to_uv(sx, sy)
        samples.append((u, v, state.client.as_tuple(), state.dpi))
        print(f"    u={u:.5f} v={v:.5f}  client={state.client.as_tuple()}  dpi={state.dpi:.2f}")

    if len(samples) < 2:
        print("\nFAIL: need at least 2 usable rounds")
        return 1

    us = [s[0] for s in samples]
    vs = [s[1] for s in samples]
    spread_u = max(us) - min(us)
    spread_v = max(vs) - min(vs)
    positions = {s[2] for s in samples}
    scales = {round(s[3], 4) for s in samples}

    print(f"\nrounds={len(samples)}  distinct window positions={len(positions)}")
    print(f"dpi scale(s) seen: {sorted(scales)}")
    print(f"spread  u={spread_u:.5f}  v={spread_v:.5f}  (tolerance {TOLERANCE})")

    ok = spread_u < TOLERANCE and spread_v < TOLERANCE
    if len(positions) < 2:
        print("WARN: the window never actually moved -- this proves nothing")
        ok = False
    if len(scales) > 1:
        print("WARN: DPI scale changed mid-run; rerun without changing it")
        ok = False

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
