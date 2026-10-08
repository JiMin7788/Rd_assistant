"""dxcam capture loop (spec 03 §5, R2). Windows only.

Timestamps are taken immediately after ``grab()`` returns, never after the
frame reaches the encoder queue -- the queue depth varies and would smear the
one number the whole dataset is aligned on.

``grab()`` returning ``None`` means the desktop did not change, which is a
genuine duplicate frame rather than an error. It is passed on with
``dup=True`` so the builder can exclude it from training.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .geometry import Rect

__all__ = ["Frame", "CaptureLoop"]


@dataclass
class Frame:
    """One captured frame. The session-global index ``i`` is assigned by the
    encoder, which is the single writer of ``frames.jsonl`` -- keeping the
    counter in one place is what guarantees the log has no gaps."""

    t: float
    dup: bool
    data: object  # HxWx3 BGR ndarray


class CaptureLoop:
    """Paced dxcam grab loop feeding a bounded queue.

    Overflow policy: drop the frame and report a stall. Blocking would delay
    the next ``grab()`` and make ``t`` mean something different from one frame
    to the next, which is worse than a gap -- the gap is visible in ``t``.
    """

    def __init__(
        self,
        region: Rect,
        target_fps: int,
        out_q: "queue.Queue[Frame]",
        on_warn: Callable[[str, dict], None],
        monitor_index: int = 0,
    ) -> None:
        self.region = region
        self.target_fps = target_fps
        self.period = 1.0 / target_fps
        self.out_q = out_q
        self.on_warn = on_warn
        self.monitor_index = monitor_index

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._camera = None

        self.n_grabbed = 0
        self.n_dup = 0
        self.n_stalled = 0
        self.last_fps = 0.0

    def start(self) -> None:
        import dxcam  # imported here so non-Windows tooling can load the module

        self._camera = dxcam.create(output_idx=self.monitor_index, output_color="BGR")
        if self._camera is None:
            raise RuntimeError(f"dxcam: no output at index {self.monitor_index}")
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        if self._camera is not None:
            try:
                self._camera.release()
            except Exception:
                pass

    def _run(self) -> None:
        region = self.region.as_tuple()
        last: object | None = None
        next_at = time.perf_counter()
        window_start = next_at
        window_frames = 0

        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_at:
                time.sleep(min(next_at - now, self.period))
                continue
            # Skip missed slots rather than bursting to catch up.
            next_at += self.period * max(1, int((now - next_at) / self.period) + 1)

            raw = self._camera.grab(region=region)  # type: ignore[union-attr]
            t = time.perf_counter()

            dup = raw is None
            if dup:
                if last is None:
                    continue  # nothing to duplicate yet
                data = last
            else:
                data = raw
                last = raw

            try:
                self.out_q.put_nowait(Frame(t=t, dup=dup, data=data))
            except queue.Full:
                self.n_stalled += 1
                self.on_warn(
                    "queue_stall",
                    {"grabbed": self.n_grabbed, "dropped": self.n_stalled},
                )
                continue

            self.n_grabbed += 1
            if dup:
                self.n_dup += 1

            window_frames += 1
            if t - window_start >= 5.0:
                self.last_fps = window_frames / (t - window_start)
                window_start, window_frames = t, 0
