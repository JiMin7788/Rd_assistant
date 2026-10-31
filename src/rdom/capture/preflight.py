"""Start check before a bot starts: are the game window(s) there, placed, uncovered, reachable.

check() reads the screen and (LD) runs read-only adb queries; it never injects input and never
saves a frame. Every outside effect is an injectable seam so tests run on fakes.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from rdom import profile as profiles
from rdom.capture import live
from rdom.input.inject import parse_wm_size, resolve_device
from rdom.recorder import window
from rdom.recorder.config import load_config

ROOT = Path(__file__).resolve().parents[3]

# The reason texts shown to the user (spec R12 'start-check reasons').
MISSING = {
    "ld": "LD플레이어 창이 없어요",
    "gpg": "구글플레이게임즈 랜덤 다이스 창이 없어요",
}
LABEL = {"ld": "LD플레이어", "gpg": "구글플레이게임즈 랜덤 다이스"}
MANY = "{title_re} 창이 2개 이상이에요"
COVERED = "다른 창이 게임 화면을 가리고 있어요"
NO_ADB = "LD플레이어 adb 연결이 안 돼요 (LD 설정 → 기타 설정 → ADB 디버깅: 로컬 연결)"
OVERLAP = "두 게임 창이 겹쳐요"
OVERLAP_OK = "두 게임 창이 겹치지 않아요"


def adb_probe(adb, serial):
    """True if `adb devices` yields a device and `adb shell wm size` reports a size.

    AI-NOTE: read-only, and output goes through temp files, never pipes: an adb pipe
    deadlocks on Windows (see AdbInjector._run in rdom.input.inject)."""
    try:
        device = resolve_device(adb, serial)
        with tempfile.TemporaryFile() as fh:
            subprocess.run([adb, "-s", device, "shell", "wm", "size"],
                           stdout=fh, stderr=subprocess.DEVNULL, timeout=10)
            fh.seek(0)
            text = fh.read().decode("utf-8", "replace")
        return parse_wm_size(text) is not None
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def _find_reason(name, title_re, finder):
    """None when exactly one window matches, else the reason text."""
    try:
        finder(title_re)
    except RuntimeError as e:
        # AI-NOTE: find_window raises "N windows match ..." for several hits and
        # "no visible window ..." for none; both are RuntimeError.
        if re.match(r"\d+ windows match", str(e)):
            return MANY.format(title_re=title_re)
        return MISSING[name]
    return None


def check(profile_names, place=True, grab=False, *, finder=None, placer=None,
          grabber_factory=None, adb_probe=adb_probe):
    """Check each profile in order; returns [(name, ok, reason)].

    Per profile the first failing step ends it: window found once, placed (place=True),
    unobscured, adb reachable (backend adb only), one frame grabbed (grab=True). With two
    profiles a last entry ("overlap", ...) compares the two content rects."""
    finder = finder or window.find_window
    placer = placer or live.place_game_window
    grabber_factory = grabber_factory or live.LiveGrabber
    results, rects, grabbers = [], {}, []
    try:
        for name in profile_names:
            prof = profiles.get(name)
            cfg_path = str(ROOT / prof.config)
            cfg = load_config(cfg_path)
            why = _find_reason(name, cfg.target.window_title_re, finder)
            if why is None:
                if place:
                    placer(cfg_path)
                g = grabber_factory(cfg_path)
                grabbers.append(g)
                if not g.unobscured():
                    why = COVERED
                elif cfg.input.backend == "adb" and not adb_probe(cfg.input.adb, cfg.input.serial):
                    why = NO_ADB
                else:
                    rects[name] = g.content_rect()[0]
                    if grab and g.grab() is None:
                        why = f"{LABEL[name]} 화면을 읽을 수 없어요"
            results.append((name, why is None, why or f"{LABEL[name]} 준비됐어요"))
        if len(profile_names) == 2 and all(n in rects for n in profile_names):
            a, b = (rects[n] for n in profile_names)
            hit = live.rects_cover(a, [b])
            results.append(("overlap", not hit, OVERLAP if hit else OVERLAP_OK))
    finally:
        for g in grabbers:
            close = getattr(g, "close", None)
            if close:
                close()
    return results


def format_lines(results):
    return [f"start check: {'OK' if ok else 'FAIL'} {reason}" for _, ok, reason in results]
