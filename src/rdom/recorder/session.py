"""Session directory, environment fingerprint, and jsonl writers.

Spec 03 §2.3, §3.3. Stdlib only.

The fingerprint is the reason ``session.json`` exists: the dataset builder
refuses to mix sessions whose environments differ, because a resolution or DPI
change silently invalidates every template and every normalized coordinate
comparison across the boundary.
"""

from __future__ import annotations

import hashlib
import json
import queue
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_VERSION", "JsonlWriter", "Session", "env_fingerprint"]

SCHEMA_VERSION = 2

#: Keys that define whether two sessions are compatible. Anything not listed
#: here (window position on screen, monitor index) does not affect the data
#: because coordinates are normalized to the content area.
FINGERPRINT_KEYS = (
    "emulator.name",
    "emulator.version",
    "android_res",
    "android_dpi",
    "game_version",
    "game_gfx_preset",
    "chrome",
    "letterbox",
    "win_dpi_scale",
    "capture.out_res",
    "capture.covers",
)


def _dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def env_fingerprint(env: dict, capture: dict) -> str:
    merged = dict(env)
    merged["capture"] = capture
    payload = {k: _dig(merged, k) for k in FINGERPRINT_KEYS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class JsonlWriter:
    """Single-consumer append-only jsonl writer on its own thread.

    One writer per file means no lock is shared between the encoder and the
    event processor. Events are never dropped -- losing one action costs far
    more than losing one frame.
    """

    _SENTINEL = object()

    def __init__(self, path: Path, flush_every: int = 200) -> None:
        self.path = path
        self._q: queue.Queue = queue.Queue()
        self._flush_every = flush_every
        self._fh = open(path, "a", encoding="utf-8", buffering=1 << 16)
        self._thread = threading.Thread(target=self._run, name=f"w:{path.name}", daemon=True)
        self._thread.start()
        self.n_written = 0

    def write(self, obj: dict) -> None:
        self._q.put(obj)

    def _run(self) -> None:
        pending = 0
        while True:
            obj = self._q.get()
            if obj is self._SENTINEL:
                break
            self._fh.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
            self._fh.write("\n")
            self.n_written += 1
            pending += 1
            if pending >= self._flush_every:
                self._fh.flush()
                pending = 0
        self._fh.flush()
        self._fh.close()

    def close(self, timeout: float = 30.0) -> None:
        self._q.put(self._SENTINEL)
        self._thread.join(timeout)


@dataclass
class Session:
    """Owns the session directory and the two jsonl streams."""

    root: Path
    session_id: str
    frames: JsonlWriter
    events: JsonlWriter
    started_wall: str

    @classmethod
    def create(cls, data_root: Path) -> "Session":
        now = datetime.now().astimezone()
        session_id = f"{now:%Y-%m-%d_%H%M}_{secrets.token_hex(2)}"
        root = Path(data_root) / session_id
        (root / "video").mkdir(parents=True, exist_ok=False)
        (root / "calib").mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            session_id=session_id,
            frames=JsonlWriter(root / "frames.jsonl"),
            events=JsonlWriter(root / "events.jsonl"),
            started_wall=now.isoformat(),
        )

    @property
    def video_dir(self) -> Path:
        return self.root / "video"

    def write_manifest(
        self,
        env: dict,
        capture: dict,
        calib: dict | None,
        result: dict,
    ) -> Path:
        doc = {
            "session_id": self.session_id,
            "schema_version": SCHEMA_VERSION,
            "started_wall": self.started_wall,
            "clock": "perf_counter",
            "env_fingerprint": env_fingerprint(env, capture),
            "env": env,
            "capture": capture,
            "calib": calib,
            "result": result,
        }
        path = self.root / "session.json"
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def close(self) -> None:
        self.frames.close()
        self.events.close()
