"""Pure input-event handling: raw pointer events -> tap/drag actions.

Spec 03 §3.2, §4.2, §4.3. No platform dependencies.

Two things are emitted for every gesture:

* the **raw** ``mouse_down`` / ``mouse_move`` / ``mouse_up`` events, so the
  tap/drag threshold can be changed later and the data re-interpreted;
* the **interpreted** ``action``, whose ``t`` is the *mouse_down* time -- the
  moment the human committed to the decision, not when they released.

Nothing here applies capture-latency or human-reaction-delay correction.
Those belong to the dataset builder (spec §1.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .geometry import Viewport, dist_n

__all__ = ["Pointer", "Action", "classify", "PointerTracker"]

DOWN = "down"
MOVE = "move"
UP = "up"


@dataclass(frozen=True)
class Pointer:
    """One raw pointer sample, already converted to normalized coords."""

    t: float
    kind: str  # DOWN | MOVE | UP
    sx: int
    sy: int
    u: float
    v: float

    def to_json(self) -> dict:
        return {
            "t": round(self.t, 6),
            "ev": f"mouse_{self.kind}",
            "sx": self.sx,
            "sy": self.sy,
            "u": round(self.u, 6),
            "v": round(self.v, 6),
        }


@dataclass(frozen=True)
class Action:
    """An interpreted gesture. ``t`` is the press time, ``t_end`` the release."""

    kind: str  # "tap" | "drag"
    t: float
    t_end: float
    u0: float
    v0: float
    u1: float
    v1: float
    path_n: int
    dist_n: float

    @property
    def dur_ms(self) -> float:
        return (self.t_end - self.t) * 1000.0

    def to_json(self) -> dict:
        base = {
            "t": round(self.t, 6),
            "ev": "action",
            "kind": self.kind,
            "t_end": round(self.t_end, 6),
            "dur_ms": round(self.dur_ms, 3),
            "path_n": self.path_n,
            "dist_n": round(self.dist_n, 6),
        }
        if self.kind == "tap":
            base["at"] = {"u": round(self.u0, 6), "v": round(self.v0, 6)}
        else:
            base["from"] = {"u": round(self.u0, 6), "v": round(self.v0, 6)}
            base["to"] = {"u": round(self.u1, 6), "v": round(self.v1, 6)}
        return base


def classify(
    down: Pointer,
    moves: Iterable[Pointer],
    up: Pointer,
    tap_radius_n: float,
) -> Action:
    """Turn a down/move*/up sequence into one Action.

    Duration is recorded but deliberately NOT used to decide tap vs drag: a
    long-press may be a distinct in-game action, and that call belongs to the
    builder once §13 of the spec is answered.
    """
    d = dist_n(down.u, down.v, up.u, up.v)
    return Action(
        kind="tap" if d < tap_radius_n else "drag",
        t=down.t,
        t_end=up.t,
        u0=down.u,
        v0=down.v,
        u1=up.u,
        v1=up.v,
        path_n=sum(1 for _ in moves),
        dist_n=d,
    )


class PointerTracker:
    """Stateful consumer of raw OS pointer events.

    Feed it screen-space events; it converts, filters and emits. Discard rules
    follow spec §4.3: anything outside the content area is dropped entirely,
    and events are ignored while paused.
    """

    def __init__(
        self,
        viewport: Viewport,
        tap_radius_n: float,
        move_throttle_ms: float,
        on_raw: Callable[[Pointer], None],
        on_action: Callable[[Action], None],
        record_moves_while_down: bool = True,
    ) -> None:
        self.viewport = viewport
        self.tap_radius_n = tap_radius_n
        self.move_throttle_s = move_throttle_ms / 1000.0
        self.record_moves_while_down = record_moves_while_down
        self._on_raw = on_raw
        self._on_action = on_action

        self._down: Pointer | None = None
        self._moves: list[Pointer] = []
        self._last_move_t = 0.0
        self.paused = False

        # counters surfaced in the end-of-session report (spec §8)
        self.n_actions = 0
        self.n_orphan_down = 0
        self.n_orphan_up = 0
        self.n_outside = 0

    # -- entry points -----------------------------------------------------

    def feed(self, t: float, kind: str, sx: int, sy: int) -> None:
        if self.paused:
            return
        if not self.viewport.contains(sx, sy):
            self.n_outside += 1
            # A press that started inside but was released outside still has to
            # close the gesture, otherwise the tracker deadlocks on that press.
            # The resulting action carries u1/v1 outside [0,1); the builder
            # decides whether to keep such a drag.
            if kind == UP and self._down is not None:
                p = self._make(t, UP, sx, sy)
                self._on_raw(p)
                self._close(p)
            return

        p = self._make(t, kind, sx, sy)

        if kind == DOWN:
            if self._down is not None:
                self.n_orphan_down += 1  # previous press never released
            self._down = p
            self._moves = []
            self._last_move_t = t
            self._on_raw(p)

        elif kind == MOVE:
            if self._down is None or not self.record_moves_while_down:
                return
            if t - self._last_move_t < self.move_throttle_s:
                return
            self._last_move_t = t
            self._moves.append(p)
            self._on_raw(p)

        elif kind == UP:
            if self._down is None:
                self.n_orphan_up += 1
                return
            self._on_raw(p)
            self._close(p)

    def close(self) -> None:
        """Session end: an unreleased press is dropped, not guessed."""
        if self._down is not None:
            self.n_orphan_down += 1
            self._down = None
            self._moves = []

    # -- internals --------------------------------------------------------

    def _make(self, t: float, kind: str, sx: int, sy: int) -> Pointer:
        u, v = self.viewport.to_uv(sx, sy)
        return Pointer(t=t, kind=kind, sx=sx, sy=sy, u=u, v=v)

    def _close(self, up: Pointer) -> None:
        assert self._down is not None
        action = classify(self._down, self._moves, up, self.tap_radius_n)
        self._down = None
        self._moves = []
        self.n_actions += 1
        self._on_action(action)
