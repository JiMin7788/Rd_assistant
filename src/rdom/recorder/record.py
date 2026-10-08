"""Recorder entry point: preflight, thread wiring, watchdog, self-verify.

    python -m rdom.recorder.record --config config/recorder.toml \
        --emulator-version 9.1.34 --game-version 1.4.2

Hotkeys: F9 episode begin/end, F10 discard last episode, F11 pause, F12 stop.

The watchdog is deliberately unforgiving. Recording on through a window move
would corrupt the session silently, and a silent corruption is only discovered
after the data has been collected -- so a broken invariant stops the session
and keeps whatever was recorded up to that point (spec §1.3, §7).
"""

from __future__ import annotations

import argparse
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

from .capture import CaptureLoop
from .config import RecorderConfig, load_config
from .encoder import SegmentEncoder, plan_out_res, probe_encoder
from .events import PointerTracker
from .frames_index import load_frames
from .geometry import Insets, Viewport, detect_letterbox, fit_chrome
from .hook import HotkeyHook, PointerHook
from .session import Session
from .verify import VerifyReport, verify_events, verify_frames, verify_segments

__all__ = ["Recorder", "main"]


class Recorder:
    def __init__(self, cfg: RecorderConfig, meta: dict) -> None:
        self.cfg = cfg
        self.meta = meta
        self.t0 = time.perf_counter()

        self.hwnd: int = 0
        self.viewport: Viewport | None = None
        self.session: Session | None = None
        self.capture: CaptureLoop | None = None
        self.encoder: SegmentEncoder | None = None
        self.tracker: PointerTracker | None = None

        self._stop = threading.Event()
        self._fatal: str | None = None
        self._episode = 0
        self._in_episode = False
        self._paused = False
        self._codec = cfg.capture.codec
        self._out_res: tuple[int, int] = (0, 0)

    # -- event helpers ----------------------------------------------------

    def _emit(self, obj: dict) -> None:
        if self.session is not None:
            self.session.events.write({"t": round(time.perf_counter(), 6), **obj})

    def _warn(self, code: str, extra: dict | None = None) -> None:
        self._emit({"ev": "warn", "code": code, **(extra or {})})

    def _fatal_stop(self, code: str, extra: dict | None = None) -> None:
        self._fatal = code
        self._emit({"ev": "fatal", "code": code, **(extra or {})})
        self._stop.set()

    # -- preflight --------------------------------------------------------

    def preflight(self) -> "WindowState":  # type: ignore[name-defined]
        from .window import WindowState, find_window, set_dpi_awareness

        set_dpi_awareness()  # must precede every rect read
        self.hwnd = find_window(self.cfg.target.window_title_re)
        state = WindowState.read(self.hwnd)

        if state.minimized:
            raise RuntimeError("emulator window is minimized")
        if abs(state.dpi - 1.0) > 1e-6:
            print(
                f"[warn] Windows display scaling is {state.dpi:.2%}. "
                "100% is strongly recommended; coordinates stay correct but "
                "capture is resampled.",
                file=sys.stderr,
            )

        self._codec = probe_encoder(self.cfg.capture.codec)
        if self._codec != self.cfg.capture.codec:
            print(f"[warn] {self.cfg.capture.codec} unavailable -> {self._codec}", file=sys.stderr)

        free_gb = shutil.disk_usage(self.cfg.data_root.parent if self.cfg.data_root.parent.exists()
                                    else Path(".")).free / 1e9
        if free_gb < self.cfg.limits.min_disk_gb:
            raise RuntimeError(
                f"only {free_gb:.1f} GB free, need {self.cfg.limits.min_disk_gb} GB"
            )
        return state

    def measure_letterbox(self, rect) -> Insets:
        """Grab one frame of ``rect`` to find black bars before recording.

        ``rect`` is the client area with chrome already removed: probing the
        raw client would feed the emulator's tab bar to the black-bar scan.
        """
        import dxcam

        cam = dxcam.create(output_idx=self.cfg.capture.monitor_index, output_color="BGR")
        if cam is None:
            raise RuntimeError(f"dxcam: no output at index {self.cfg.capture.monitor_index}")
        try:
            region = self._to_output_region(rect)
            frame = None
            for _ in range(30):
                frame = cam.grab(region=region.as_tuple())
                if frame is not None:
                    break
                time.sleep(0.05)
            if frame is None:
                raise RuntimeError("dxcam returned no frame during letterbox probe")
            if self.session is not None:
                self._save_probe(frame)
            return detect_letterbox(frame)
        finally:
            cam.release()

    def _to_output_region(self, client):
        """dxcam regions are relative to the output, not the virtual desktop."""
        from .window import monitor_info

        mon = monitor_info(self.hwnd)
        return client.translated(-mon["rect"][0], -mon["rect"][1])

    def _save_probe(self, frame) -> None:
        """First frame as PNG for eyeball verification (spec §2.3)."""
        assert self.session is not None
        try:
            import numpy as np
            from PIL import Image

            Image.fromarray(np.asarray(frame)[:, :, ::-1]).save(
                self.session.root / "calib" / "first_frame.png"
            )
        except Exception:
            pass  # optional aid, never worth failing the session for

    # -- hotkeys ----------------------------------------------------------

    def _toggle_episode(self) -> None:
        if self._in_episode:
            self._emit({"ev": "episode_end", "n": self._episode})
            self._in_episode = False
            print(f"[episode {self._episode} END]")
        else:
            self._episode += 1
            self._emit({"ev": "episode_begin", "n": self._episode})
            self._in_episode = True
            print(f"[episode {self._episode} BEGIN]")

    def _discard_episode(self) -> None:
        if self._episode:
            self._emit({"ev": "episode_discard", "n": self._episode, "why": "hotkey"})
            print(f"[episode {self._episode} DISCARDED]")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        if self.tracker is not None:
            self.tracker.paused = self._paused
        self._emit({"ev": "pause" if self._paused else "resume"})
        print("[PAUSED]" if self._paused else "[RESUMED]")

    # -- run --------------------------------------------------------------

    def run(self) -> int:
        from .window import WindowState

        state = self.preflight()
        cfg = self.cfg

        self.session = Session.create(cfg.data_root)
        print(f"session: {self.session.root}")

        # Chrome comes off first, then the letterbox scan runs on what is left.
        chrome = fit_chrome(state.client, cfg.target.chrome)
        bare = Viewport(client=state.client, chrome=chrome)
        letterbox = self.measure_letterbox(bare.inner)
        self.viewport = Viewport(
            client=state.client, chrome=chrome, letterbox=letterbox
        )
        content = self.viewport.content
        self._out_res = plan_out_res(
            content.width, content.height, cfg.capture.out_long_edge
        )
        print(
            f"client {state.client.width}x{state.client.height}"
            f"  chrome {chrome.as_dict()}"
            f"  letterbox {letterbox.as_dict()}"
        )
        print(
            f"content {content.width}x{content.height}"
            f" -> encoding {self._out_res[0]}x{self._out_res[1]}"
        )
        if cfg.target.chrome == Insets():
            print(
                "[warn] chrome insets are all zero -- if the emulator draws a tab bar "
                "or sidebar, it is being recorded as if it were part of the game. "
                "Measure with tools/verify/g2b_chrome.py.",
                file=sys.stderr,
            )

        frame_q: queue.Queue = queue.Queue(maxsize=cfg.capture.queue_frames)
        pointer_q: queue.Queue = queue.Queue()

        self.encoder = SegmentEncoder(
            in_q=frame_q,
            video_dir=self.session.video_dir,
            frames_writer=self.session.frames,
            src_res=(content.width, content.height),
            out_res=self._out_res,
            fps=cfg.capture.target_fps,
            codec=self._codec,
            crf=cfg.capture.crf,
            segment_frames=cfg.capture.segment_frames,
            on_warn=self._warn,
        )
        self.capture = CaptureLoop(
            region=self._to_output_region(content),
            target_fps=cfg.capture.target_fps,
            out_q=frame_q,
            on_warn=self._warn,
            monitor_index=cfg.capture.monitor_index,
        )
        self.tracker = PointerTracker(
            viewport=self.viewport,
            tap_radius_n=cfg.input.tap_radius_n,
            move_throttle_ms=cfg.input.move_throttle_ms,
            record_moves_while_down=cfg.input.record_moves_while_down,
            on_raw=lambda p: self.session.events.write(p.to_json()),  # type: ignore[union-attr]
            on_action=lambda a: self.session.events.write(a.to_json()),  # type: ignore[union-attr]
        )

        pointer_hook = PointerHook(pointer_q)
        hotkeys = HotkeyHook({
            cfg.hotkeys.episode_toggle: self._toggle_episode,
            cfg.hotkeys.discard: self._discard_episode,
            cfg.hotkeys.pause: self._toggle_pause,
            cfg.hotkeys.stop: self._stop.set,
        })

        proc = threading.Thread(
            target=self._process_pointers, args=(pointer_q,), name="events", daemon=True
        )

        self.encoder.start()
        self.capture.start()
        pointer_hook.start()
        hotkeys.start()
        proc.start()

        print(
            f"recording. {cfg.hotkeys.episode_toggle}=episode  "
            f"{cfg.hotkeys.discard}=discard  {cfg.hotkeys.pause}=pause  "
            f"{cfg.hotkeys.stop}=stop"
        )
        try:
            self._watch(state, WindowState)
        except KeyboardInterrupt:
            pass
        finally:
            pointer_hook.stop()
            hotkeys.stop()
            self.capture.stop()
            pointer_q.put(None)
            proc.join(10)
            self.tracker.close()
            self.encoder.stop()

        return self._finish(state, letterbox, content)

    def _process_pointers(self, pointer_q: "queue.Queue") -> None:
        assert self.tracker is not None
        while True:
            item = pointer_q.get()
            if item is None:
                return
            t, kind, sx, sy = item
            self.tracker.feed(t, kind, sx, sy)

    def _watch(self, baseline, WindowState) -> None:
        cfg = self.cfg
        min_fps = cfg.capture.target_fps * cfg.limits.fps_warn_ratio
        last_report = 0.0

        while not self._stop.is_set():
            self._stop.wait(cfg.limits.watchdog_sec)
            if self._stop.is_set():
                break

            try:
                now_state = WindowState.read(self.hwnd)
            except Exception as exc:
                self._fatal_stop("window_lost", {"err": str(exc)})
                break

            drift = baseline.drift(now_state)
            if drift:
                self._fatal_stop(
                    "window_changed",
                    {"detail": drift,
                     "old": list(baseline.client.as_tuple()),
                     "new": list(now_state.client.as_tuple())},
                )
                break

            cap = self.capture
            assert cap is not None
            if cap.last_fps and cap.last_fps < min_fps:
                self._warn("fps_drop", {"fps": round(cap.last_fps, 2)})

            free_gb = shutil.disk_usage(self.session.root).free / 1e9  # type: ignore[union-attr]
            if free_gb < cfg.limits.min_disk_gb * 0.25:
                self._fatal_stop("disk_low", {"free_gb": round(free_gb, 2)})
                break
            if free_gb < cfg.limits.min_disk_gb:
                self._warn("disk_low", {"free_gb": round(free_gb, 2)})

            now = time.perf_counter()
            if now - last_report >= 30.0:
                last_report = now
                enc = self.encoder
                print(
                    f"  {now - self.t0:7.0f}s  frames={enc.i if enc else 0}  "
                    f"seg={enc.seg if enc else 0}  fps={cap.last_fps:.1f}  "
                    f"dup={cap.n_dup}  stall={cap.n_stalled}  "
                    f"actions={self.tracker.n_actions if self.tracker else 0}  "
                    f"episode={f'{self._episode} REC' if self._in_episode else 'off'}"
                )

    # -- shutdown ---------------------------------------------------------

    def _finish(self, state, letterbox: Insets, content) -> int:
        assert self.session is not None and self.encoder is not None
        assert self.capture is not None and self.tracker is not None

        if self._in_episode:
            self._emit({"ev": "episode_end", "n": self._episode, "note": "session stop"})
        self.session.close()

        frames = load_frames(self.session.root / "frames.jsonl")
        events = _read_jsonl(self.session.root / "events.jsonl")

        report = VerifyReport()
        for r in (
            verify_frames(frames, self.cfg.limits.max_dup_ratio),
            verify_events(events),
            verify_segments(self.session.video_dir, frames),
        ):
            report.checks.extend(r.checks)

        env = {
            "emulator": {
                "name": self.meta.get("emulator_name", "LDPlayer"),
                "version": self.meta.get("emulator_version", "unknown"),
                "instance": self.meta.get("instance", "unknown"),
            },
            "android_res": self.meta.get("android_res"),
            "android_dpi": self.meta.get("android_dpi"),
            "game_version": self.meta.get("game_version", "unknown"),
            "game_gfx_preset": self.meta.get("gfx_preset", "unknown"),
            "window_client_rect_screen": list(state.client.as_tuple()),
            "capture_region": list(self._to_output_region(content).as_tuple()),
            "chrome": self.viewport.chrome.as_dict(),
            "letterbox": letterbox.as_dict(),
            "content_res": [content.width, content.height],
            "win_dpi_scale": state.dpi,
            "monitor": {"rect": list(state.monitor_rect)},
        }
        capture_meta = {
            "backend": self.cfg.capture.backend,
            "target_fps": self.cfg.capture.target_fps,
            "codec": self._codec,
            "crf": self.cfg.capture.crf,
            "out_res": list(self._out_res),
            # The encoded video covers exactly the content area, so (u,v) maps
            # linearly onto video pixels. Tools rely on this; older sessions
            # captured the whole client and are not interchangeable.
            "covers": "content",
            "segment_sec": self.cfg.capture.segment_sec,
        }
        result = {
            "status": "FATAL" if self._fatal else report.status,
            "fatal": self._fatal,
            "frames": len(frames),
            "events": len(events),
            "dup_ratio": round(self.capture.n_dup / max(1, self.capture.n_grabbed), 5),
            "stalls": self.capture.n_stalled,
            "actions": self.tracker.n_actions,
            "orphan_down": self.tracker.n_orphan_down,
            "orphan_up": self.tracker.n_orphan_up,
            "clicks_outside": self.tracker.n_outside,
            "episodes": self._episode,
            "duration_sec": round(time.perf_counter() - self.t0, 2),
            "verify": report.to_json(),
        }
        path = self.session.write_manifest(env, capture_meta, None, result)

        print(f"\n{result['status']}  frames={len(frames)}  actions={self.tracker.n_actions}")
        for c in report.failures():
            print(f"  FAIL {c.name}: {c.detail}")
        print(f"manifest: {path}")
        return 0 if result["status"] == "OK" else 1


def _read_jsonl(path: Path) -> list[dict]:
    import json

    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rdom-record")
    ap.add_argument("--config", default="config/recorder.toml")
    ap.add_argument("--emulator-name", default="LDPlayer")
    ap.add_argument("--emulator-version", default="unknown")
    ap.add_argument("--instance", default="unknown")
    ap.add_argument("--android-res", default="", help="e.g. 1600x900")
    ap.add_argument("--android-dpi", type=int, default=0)
    ap.add_argument("--game-version", default="unknown")
    ap.add_argument("--gfx-preset", default="unknown")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    meta = {
        "emulator_name": args.emulator_name,
        "emulator_version": args.emulator_version,
        "instance": args.instance,
        "android_res": [int(x) for x in args.android_res.split("x")] if args.android_res else None,
        "android_dpi": args.android_dpi or None,
        "game_version": args.game_version,
        "gfx_preset": args.gfx_preset,
    }
    return Recorder(cfg, meta).run()


if __name__ == "__main__":
    raise SystemExit(main())
