"""R8 -- draw recorded actions back onto the video to prove the sync is right.

Spec 03 §9. Without this there is no way to know whether an action is attached
to the frame the player was actually looking at, and the answer only shows up
after the data is collected. So this is the gate before any long session.

Two markers per action, deliberately in different colours:

* **uncorrected** at the frame captured when the button went down;
* **corrected** at ``t + capture_offset_ms``, which is where the click's own
  visual feedback should appear.

Healthy output: the corrected marker sits on the thing that visibly reacts, and
the uncorrected one trails slightly behind it. If neither lands on anything, the
coordinate transform is wrong, not the offset.

    rdom-replay --session data/sessions/<id> --start-sec 120 --duration 20

Frames are selected by index from the start of the segment -- no seeking. That
makes a 10-minute segment slow to scan but keeps the frame numbering exact,
which is the entire point of the tool.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rdom.recorder.frames_index import FrameRec, load_frames

__all__ = ["Marker", "build_filter_graph", "plan_markers", "render", "main"]

MIN_SCHEMA = 2
MARK_HOLD = 3  # frames a marker stays visible
UNCORRECTED = "red"
CORRECTED = "lime"

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)


@dataclass(frozen=True)
class Marker:
    local_frame: int  # frame index within the extracted clip
    x: int
    y: int
    color: str
    label: str


def _find_font() -> str | None:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_session(session_dir: Path) -> dict:
    doc = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    if doc.get("schema_version", 0) < MIN_SCHEMA:
        raise SystemExit(
            f"session schema v{doc.get('schema_version')} is too old for this tool "
            f"(need v{MIN_SCHEMA}+). Older sessions recorded the whole emulator "
            "window instead of the game content, so (u,v) does not map onto the "
            "video. Re-record after the chrome-inset fix."
        )
    covers = doc.get("capture", {}).get("covers")
    if covers != "content":
        raise SystemExit(
            f"capture.covers is {covers!r}, expected 'content' -- this video does "
            "not correspond 1:1 to the normalized coordinate space."
        )
    return doc


def frame_index_at(frames: list[FrameRec], t: float) -> int | None:
    """Index into ``frames`` of the last frame captured at or before ``t``."""
    from bisect import bisect_right

    times = [f.t for f in frames]
    k = bisect_right(times, t) - 1
    return k if k >= 0 else None


def plan_markers(
    frames: list[FrameRec],
    events: list[dict],
    i0: int,
    i1: int,
    out_w: int,
    out_h: int,
    offset_ms: float,
) -> list[Marker]:
    """Markers for every action landing in the clip's frame window [i0, i1)."""
    markers: list[Marker] = []
    offset = offset_ms / 1000.0

    for ev in events:
        if ev.get("ev") != "action":
            continue
        point = ev.get("at") or ev.get("from") or {}
        if "u" not in point:
            continue
        x = int(point["u"] * out_w)
        y = int(point["v"] * out_h)
        kind = ev.get("kind", "?")

        for t, color, tag in (
            (ev["t"], UNCORRECTED, kind),
            (ev["t"] + offset, CORRECTED, f"{kind}+{offset_ms:.0f}ms"),
        ):
            k = frame_index_at(frames, t)
            if k is None or not (i0 <= k < i1):
                continue
            markers.append(
                Marker(local_frame=k - i0, x=x, y=y, color=color, label=tag)
            )
    return markers


def build_filter_graph(
    markers: list[Marker],
    frames: list[FrameRec],
    i0: int,
    i1: int,
    out_w: int,
    out_h: int,
    font: str | None,
) -> str:
    """One drawbox per marker, plus a dup-frame flag and a frame-number HUD."""
    size = max(24, out_w // 18)
    half = size // 2
    parts: list[str] = []

    for m in markers:
        x = max(0, min(out_w - size, m.x - half))
        y = max(0, min(out_h - size, m.y - half))
        lo, hi = m.local_frame, m.local_frame + MARK_HOLD
        parts.append(
            f"drawbox=x={x}:y={y}:w={size}:h={size}:color={m.color}@0.95:t=3"
            f":enable='between(n\\,{lo}\\,{hi})'"
        )

    # Duplicated frames get a corner flag: a marker sitting on a run of dups is
    # evidence the capture stalled, not that the offset is wrong.
    dup_local = [f.i - i0 for f in frames[i0:i1] if f.dup]
    for n in dup_local:
        parts.append(
            f"drawbox=x={out_w - 18}:y=2:w=16:h=16:color=orange@0.9:t=fill"
            f":enable='eq(n\\,{n})'"
        )

    if font:
        fp = font.replace("\\", "/").replace(":", "\\:")
        parts.append(
            f"drawtext=fontfile='{fp}'"
            f":text='f=%{{eif\\:n+{i0}\\:d}}  clip=%{{n}}'"
            f":x=6:y=6:fontsize={max(14, out_w // 40)}"
            ":fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=4"
        )
    return ",".join(parts) if parts else "null"


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({proc.returncode}):\n{proc.stderr[-2000:]}")


def render(
    session_dir: Path,
    out_path: Path,
    start_frame: int,
    n_frames: int,
    offset_ms: float,
) -> dict:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH")

    doc = load_session(session_dir)
    out_w, out_h = doc["capture"]["out_res"]
    frames = load_frames(session_dir / "frames.jsonl")
    events = _read_jsonl(session_dir / "events.jsonl")

    i0 = start_frame
    i1 = min(start_frame + n_frames, len(frames))
    if i0 >= i1:
        raise SystemExit(f"empty window: frames={len(frames)} start={i0}")

    seg = frames[i0].seg
    if frames[i1 - 1].seg != seg:
        boundary = next(f.i for f in frames[i0:i1] if f.seg != seg)
        raise SystemExit(
            f"window spans segments {seg}..{frames[i1 - 1].seg}; pick a start "
            f"before frame {boundary - n_frames} or after {boundary}"
        )

    src = session_dir / "video" / f"seg_{seg:05d}.mp4"
    if not src.exists():
        raise SystemExit(f"missing {src}")

    a, b = frames[i0].si, frames[i1 - 1].si
    markers = plan_markers(frames, events, i0, i1, out_w, out_h, offset_ms)
    graph = build_filter_graph(markers, frames, i0, i1, out_w, out_h, _find_font())

    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-vf", f"select='between(n\\,{a}\\,{b})',setpts=N/FRAME_RATE/TB",
            "-fps_mode", "passthrough", "-c:v", "libx264", "-crf", "18",
            "-pix_fmt", "yuv420p", str(clip),
        ])
        # The graph goes in a file: a few hundred markers easily exceed the
        # 8191-character command line limit on Windows.
        script = Path(tmp) / "graph.txt"
        script.write_text(graph, encoding="utf-8")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
            # -filter_script was removed in ffmpeg 9; -/filter reads the same file
            "-/filter:v", str(script),
            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
            "-fps_mode", "passthrough", str(out_path),
        ])

    return {
        "out": str(out_path),
        "segment": seg,
        "frames": i1 - i0,
        "frame_range": [i0, i1 - 1],
        "segment_range": [a, b],
        "markers": len(markers),
        "actions": len(markers) // 2,
        "dups": sum(1 for f in frames[i0:i1] if f.dup),
        "offset_ms": offset_ms,
        "out_res": [out_w, out_h],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rdom-replay")
    ap.add_argument("--session", required=True, type=Path)
    ap.add_argument("--start-sec", type=float, default=None,
                    help="seconds from the first captured frame")
    ap.add_argument("--start-frame", type=int, default=None)
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--offset-ms", type=float, default=None,
                    help="capture latency; defaults to calib.capture_offset_ms, else 0")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    doc = load_session(args.session)
    fps = doc["capture"]["target_fps"]

    offset = args.offset_ms
    if offset is None:
        offset = (doc.get("calib") or {}).get("capture_offset_ms", 0.0)
        if not offset:
            print(
                "[warn] no calibration offset available; corrected markers will "
                "coincide with uncorrected ones. Run R6 first for a real check.",
                file=sys.stderr,
            )

    if args.start_frame is not None:
        start = args.start_frame
    elif args.start_sec is not None:
        start = int(args.start_sec * fps)
    else:
        start = 0

    out = args.out or (args.session / f"overlay_{start}.mp4")
    info = render(args.session, out, start, int(args.duration * fps), float(offset))
    print(json.dumps(info, indent=2))
    print(
        "\nWatch it: the green marker should sit on whatever visibly reacts to "
        "the click, with red trailing just behind. If neither lands on anything, "
        "the coordinate transform is wrong, not the offset."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
