"""ffmpeg segment encoder and the sole writer of ``frames.jsonl`` (R3).

Segmentation is done here rather than with ffmpeg's ``segment`` muxer because
we must know exactly which segment each frame landed in. Letting ffmpeg decide
boundaries would leave ``seg``/``si`` guessed, and a guess here mislabels every
action in the session (spec §2.2).

Rotating the process costs ~100ms; the bounded capture queue absorbs it, so no
frame is lost at a boundary. The retiring process is drained on a reaper thread
so a 10-minute segment never blocks the loop while it flushes.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .capture import Frame
from .frames_index import FrameRec
from .session import JsonlWriter

__all__ = ["SegmentEncoder", "build_ffmpeg_cmd", "probe_encoder", "plan_out_res"]


def plan_out_res(src_w: int, src_h: int, long_edge: int) -> tuple[int, int]:
    """Scale the capture to ``long_edge`` on its longer side, aspect preserved.

    The output resolution is derived rather than configured because a hardcoded
    pair silently stretches the recording the moment the emulator window is a
    different shape -- a portrait 1499x2108 capture forced into 720x1280
    squeezes the picture horizontally by 21% and nothing reports it.

    Both edges are rounded to even numbers, which yuv420p requires.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"bad source resolution {src_w}x{src_h}")

    if src_w >= src_h:
        out_w = min(long_edge, src_w)
        out_h = round(out_w * src_h / src_w)
    else:
        out_h = min(long_edge, src_h)
        out_w = round(out_h * src_w / src_h)

    even = lambda v: max(2, v - (v % 2))
    return even(out_w), even(out_h)


def build_ffmpeg_cmd(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    fps: int,
    codec: str,
    crf: int,
    out_path: Path,
) -> list[str]:
    """Raw BGR on stdin, scaled and encoded to a single-segment mp4.

    Scaling is delegated to ffmpeg so the capture thread never touches pixels.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{src_w}x{src_h}", "-r", str(fps),
        "-i", "-",
    ]
    if (src_w, src_h) != (out_w, out_h):
        cmd += ["-vf", f"scale={out_w}:{out_h}:flags=bicubic"]
    if codec == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", str(crf)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf)]
    cmd += ["-pix_fmt", "yuv420p", "-fps_mode", "passthrough", str(out_path)]
    return cmd


def probe_encoder(preferred: str) -> str:
    """Return ``preferred`` if ffmpeg lists it, else fall back to libx264."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    if preferred == "libx264":
        return preferred
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=30,
    )
    return preferred if preferred in out.stdout else "libx264"


class SegmentEncoder:
    """Consumes frames, writes mp4 segments and one ``frames.jsonl`` line each."""

    _SENTINEL = object()

    def __init__(
        self,
        in_q: "queue.Queue",
        video_dir: Path,
        frames_writer: JsonlWriter,
        src_res: tuple[int, int],
        out_res: tuple[int, int],
        fps: int,
        codec: str,
        crf: int,
        segment_frames: int,
        on_warn: Callable[[str, dict], None],
    ) -> None:
        self.in_q = in_q
        self.video_dir = video_dir
        self.frames_writer = frames_writer
        self.src_res = src_res
        self.out_res = out_res
        self.fps = fps
        self.codec = codec
        self.crf = crf
        self.segment_frames = segment_frames
        self.on_warn = on_warn

        self._proc: subprocess.Popen | None = None
        self._reapers: list[threading.Thread] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.i = 0  # session-global frame index -- authoritative
        self.seg = 0
        self.si = 0

    def start(self) -> None:
        self._open_segment()
        self._thread = threading.Thread(target=self._run, name="encoder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 120.0) -> None:
        """Drain the queue, close the last segment, wait for every reaper."""
        self.in_q.put(self._SENTINEL)
        if self._thread:
            self._thread.join(timeout)
        self._close_segment()
        for r in self._reapers:
            r.join(timeout)

    # -- internals --------------------------------------------------------

    def _open_segment(self) -> None:
        path = self.video_dir / f"seg_{self.seg:05d}.mp4"
        cmd = build_ffmpeg_cmd(
            self.src_res[0], self.src_res[1],
            self.out_res[0], self.out_res[1],
            self.fps, self.codec, self.crf, path,
        )
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.si = 0

    def _close_segment(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return

        def _reap() -> None:
            # Note: communicate() must NOT be used here -- it re-flushes stdin
            # and raises once we have closed it, which would kill this thread
            # before ffmpeg finishes and leave a truncated segment behind with
            # nothing reported. Close stdin, drain stderr to EOF, then wait.
            err = b""
            try:
                if proc.stdin:
                    proc.stdin.close()
                if proc.stderr:
                    err = proc.stderr.read()
                proc.wait()
            except Exception as exc:  # a dead reaper must never be silent
                self.on_warn("encoder_reap_failed", {"err": str(exc)})
                return
            finally:
                # A 30h session rotates ~180 segments; leaking one fd each
                # would eventually exhaust the process limit.
                if proc.stderr:
                    try:
                        proc.stderr.close()
                    except OSError:
                        pass
            if proc.returncode != 0:
                self.on_warn(
                    "encoder_exit",
                    {"rc": proc.returncode, "err": err.decode(errors="replace")[-400:]},
                )

        t = threading.Thread(target=_reap, name="reap", daemon=True)
        t.start()
        self._reapers.append(t)

    def _rotate(self) -> None:
        self._close_segment()
        self.seg += 1
        self._open_segment()

    def _run(self) -> None:
        while True:
            item = self.in_q.get()
            if item is self._SENTINEL:
                return
            frame: Frame = item

            if self.si >= self.segment_frames:
                self._rotate()

            try:
                self._proc.stdin.write(frame.data.tobytes())  # type: ignore[union-attr]
            except (BrokenPipeError, OSError) as exc:
                self.on_warn("encoder_write_failed", {"i": self.i, "err": str(exc)})
                self._stop.set()
                return

            self.frames_writer.write(
                FrameRec(i=self.i, seg=self.seg, si=self.si, t=frame.t, dup=frame.dup).to_json()
            )
            self.i += 1
            self.si += 1
