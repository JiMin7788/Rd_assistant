"""Global mouse and hotkey hooks via pynput (R4).

Why not ``adb getevent``: an emulator translates host mouse input to touch
internally, and whether that surfaces on ``/dev/input`` varies by product and
version. A Windows hook is both reliable and shares ``perf_counter()`` with the
capture thread, so the two streams need no clock reconciliation at all.

Callbacks do nothing but stamp the time and enqueue (spec §4.4). Any real work
here delays the hook, and Windows silently unhooks a listener that falls behind.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from .events import DOWN, MOVE, UP

__all__ = ["PointerHook", "HotkeyHook"]


class PointerHook:
    """Pushes ``(t, kind, sx, sy)`` tuples onto a queue. Never blocks."""

    def __init__(self, out_q: "queue.Queue[tuple]") -> None:
        self.out_q = out_q
        self._listener = None
        self._is_down = False
        self.n_events = 0

    def start(self) -> None:
        from pynput import mouse

        def on_click(x, y, button, pressed):
            t = time.perf_counter()
            if button != mouse.Button.left:
                return
            self._is_down = pressed
            self.out_q.put((t, DOWN if pressed else UP, int(x), int(y)))
            self.n_events += 1

        def on_move(x, y):
            # Filtering here (one bool test) keeps idle mouse motion from
            # flooding the queue with hundreds of events per second.
            if not self._is_down:
                return
            self.out_q.put((time.perf_counter(), MOVE, int(x), int(y)))
            self.n_events += 1

        self._listener = mouse.Listener(on_click=on_click, on_move=on_move)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()


class HotkeyHook:
    """Function-key hotkeys. F-keys only, so game input is never shadowed."""

    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        self.bindings = {k.lower(): v for k, v in bindings.items()}
        self._listener = None
        self._lock = threading.Lock()

    def start(self) -> None:
        from pynput import keyboard

        def on_press(key):
            name = getattr(key, "name", None)
            if name is None:
                return
            fn = self.bindings.get(name.lower())
            if fn is None:
                return
            # Handlers touch recorder state; serialise them and never let an
            # exception kill the listener thread.
            with self._lock:
                try:
                    fn()
                except Exception:
                    pass

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
