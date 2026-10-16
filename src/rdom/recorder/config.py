"""Typed view over ``config/recorder.toml`` (spec 03 §12). Stdlib only."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .geometry import Insets

__all__ = ["RecorderConfig", "load_config"]


@dataclass(frozen=True)
class TargetCfg:
    window_title_re: str = "^랜덤 다이스 2"
    #: Emulator window furniture, measured once with tools/verify/g2b_chrome.py.
    #: Not auto-detectable -- it is not black, so the letterbox scan misses it.
    chrome: Insets = Insets(left=0, top=0, right=0, bottom=0)


@dataclass(frozen=True)
class CaptureCfg:
    backend: str = "dxcam"
    target_fps: int = 30
    #: Long edge of the encoded video. The short edge is derived from the
    #: capture aspect so the recording is never stretched (spec 03 amend. A2).
    out_long_edge: int = 1280
    codec: str = "h264_nvenc"
    crf: int = 23
    segment_sec: int = 600
    queue_frames: int = 120
    monitor_index: int = 0  # dxcam output index, not the Windows monitor number

    @property
    def segment_frames(self) -> int:
        return self.segment_sec * self.target_fps


@dataclass(frozen=True)
class InputCfg:
    tap_radius_n: float = 0.012
    record_moves_while_down: bool = True
    move_throttle_ms: float = 8.0


@dataclass(frozen=True)
class CalibCfg:
    trials: int = 20
    button_uv: tuple[float, float] = (0.93, 0.05)
    roi_px: int = 80
    diff_threshold: float = 12.0
    max_sigma_ms: float = 15.0


@dataclass(frozen=True)
class HotkeyCfg:
    episode_toggle: str = "f9"
    discard: str = "f10"
    pause: str = "f11"
    stop: str = "f12"


@dataclass(frozen=True)
class LimitsCfg:
    max_dup_ratio: float = 0.02
    min_disk_gb: float = 20.0
    watchdog_sec: float = 5.0
    fps_warn_ratio: float = 0.8


@dataclass(frozen=True)
class RecorderConfig:
    target: TargetCfg = field(default_factory=TargetCfg)
    capture: CaptureCfg = field(default_factory=CaptureCfg)
    input: InputCfg = field(default_factory=InputCfg)
    calib: CalibCfg = field(default_factory=CalibCfg)
    hotkeys: HotkeyCfg = field(default_factory=HotkeyCfg)
    limits: LimitsCfg = field(default_factory=LimitsCfg)
    data_root: Path = Path("data/sessions")


def _pick(cls, table: dict):
    """Build a frozen dataclass from a toml table, ignoring unknown keys.

    Unknown keys are ignored rather than rejected so that a config written for
    a later milestone (calibration, builder) does not break the recorder.
    """
    fields = {f.name: f for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs = {}
    for k, v in table.items():
        if k not in fields:
            continue
        if isinstance(v, list):
            v = tuple(v)
        kwargs[k] = v
    return cls(**kwargs)


def load_config(path: str | Path) -> RecorderConfig:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    target_raw = dict(raw.get("target", {}))
    chrome_raw = target_raw.pop("chrome", {})
    target = _pick(TargetCfg, target_raw)
    target = TargetCfg(
        window_title_re=target.window_title_re,
        chrome=Insets(**{k: int(v) for k, v in chrome_raw.items()
                         if k in ("left", "top", "right", "bottom")}),
    )
    return RecorderConfig(
        target=target,
        capture=_pick(CaptureCfg, raw.get("capture", {})),
        input=_pick(InputCfg, raw.get("input", {})),
        calib=_pick(CalibCfg, raw.get("calib", {})),
        hotkeys=_pick(HotkeyCfg, raw.get("hotkeys", {})),
        limits=_pick(LimitsCfg, raw.get("limits", {})),
        data_root=Path(raw.get("data", {}).get("root", "data/sessions")),
    )
