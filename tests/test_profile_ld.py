"""rdF04 t1: LDPlayer capture profile, profile module, detectors on the LD/GPG fixtures."""
from pathlib import Path

import cv2
import pytest

from rdom import profile
from rdom.input import inject
from rdom.input.friend_coop import slot_pending, start_ready
from rdom.perception import board
from rdom.recorder.config import load_config
from rdom.recorder.geometry import Rect, Viewport, fit_chrome

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "rdf04"


def load(name):
    return cv2.cvtColor(cv2.imread(str(FIX / f"{name}.png")), cv2.COLOR_BGR2RGB)


# ---- config ---------------------------------------------------------------------------

def test_both_configs_load_with_input_backend():
    gpg = load_config(ROOT / "config" / "recorder.toml")
    ld = load_config(ROOT / "config" / "recorder_ld.toml")
    assert gpg.input.backend == "postmessage"
    assert gpg.input.adb == "" and gpg.input.serial == ""
    assert ld.input.backend == "adb"
    assert ld.input.adb == "D:\\LDPlayer\\LDPlayer14\\adb.exe"
    assert ld.input.serial == "127.0.0.1:5555"


def test_ld_target_place_and_capture():
    ld = load_config(ROOT / "config" / "recorder_ld.toml")
    assert ld.target.window_title_re == "^LDPlayer$"
    assert ld.target.place == (1736, 2200, 1154, 2082)
    assert ld.capture.monitor_index == 1
    gpg = load_config(ROOT / "config" / "recorder.toml")
    assert ld.target.place[0] + ld.target.place[2] < gpg.target.place[0]   # no overlap, left of GPG


def test_ld_chrome_gives_9_16_content_matching_fixtures():
    ld = load_config(ROOT / "config" / "recorder_ld.toml")
    client = Rect(0, 0, ld.target.place[2], ld.target.place[3])
    # AI-NOTE: the runtime content rect is Viewport(client, fit_chrome(client, chrome)) (LiveGrabber,
    # Injector), so assert that -- not place minus chrome, which fit_chrome would override.
    c = Viewport(client, fit_chrome(client, ld.target.chrome)).content
    assert (c.width, c.height) == (1122, 1994)
    assert abs(c.width / c.height / (9 / 16) - 1) < 0.01
    assert (c.left, c.top) == (16, 80)
    # the configured right inset is the one fit_chrome derives, so the toml is not misleading
    assert fit_chrome(client, ld.target.chrome).right == ld.target.chrome.right
    for n in ("ld_host_pending", "ld_host_joined_start_ready", "ld_invite_popup"):
        assert load(n).shape[:2] == (c.height, c.width)


def test_gpg_fixtures_are_content_sized():
    ref = load("gpg_host_invite_pending")
    assert ref.shape[:2] == (2224, 1244)
    assert load("gpg_invite_popup").shape == ref.shape
    assert load("gpg_joined_room").shape == ref.shape


# ---- profile module ------------------------------------------------------------------

def test_profiles():
    ld, gpg = profile.get("ld"), profile.get("gpg")
    assert (ld.bot, ld.tag, ld.config) == ("gear", "[기어]", "config/recorder_ld.toml")
    assert (gpg.bot, gpg.tag, gpg.config) == ("gear", "[기어1]", "config/recorder.toml")
    gpg2 = profile.get("gpg2")
    assert (gpg2.bot, gpg2.tag, gpg2.config) == ("gear", "[기어2]", "config/recorder_gpg2.toml")
    assert set(profile.PROFILES) == {"ld", "gpg", "gpg2"}
    with pytest.raises(KeyError):
        profile.get("nope")
    for p in (ld, gpg):
        assert (ROOT / p.config).is_file()


def test_uv_override_and_shared_constant():
    ld, gpg = profile.get("ld"), profile.get("gpg")
    assert profile.uv(ld, "COOP_UV") == (0.497, 0.823)
    assert profile.uv(gpg, "COOP_UV") == inject.COOP_UV == (0.50, 0.745)
    assert profile.uv(ld, "START_COOP_UV") == inject.START_COOP_UV


# ---- detectors on fixtures -------------------------------------------------------------

def test_ld_host_pending():
    f = load("ld_host_pending")
    assert board.is_coop_room(f)
    assert slot_pending(f)
    assert not start_ready(f)
    assert not board.is_lobby(f)


def test_ld_host_joined_start_ready():
    f = load("ld_host_joined_start_ready")
    assert start_ready(f)
    assert board.is_coop_room(f)


@pytest.mark.parametrize("name", ["gpg_invite_popup", "ld_invite_popup"])
def test_invite_popup_is_not_lobby(name):
    assert not board.is_lobby(load(name))


# ---- tap targets on the LD room fixtures -----------------------------------------------

def _patch(f, uv, r=0.015):
    """Mean RGB of the +-r (content-normalised) patch around a tap target."""
    H, W = f.shape[:2]
    u, v = uv
    return f[int((v - r) * H):int((v + r) * H), int((u - r) * W):int((u + r) * W)] \
        .reshape(-1, 3).mean(axis=0)


def test_ld_room_tap_targets():
    pending = load("ld_host_pending")
    ready = load("ld_host_joined_start_ready")
    r, g, b = _patch(pending, inject.MODAL_X_UV)
    assert r > 1.3 * g and r > 1.3 * b                        # red close X (white cross inside)
    r, g, b = _patch(ready, inject.START_COOP_UV)
    assert r > 200 and g > 150 and r - b > 60                  # yellow 협동 시작 (label text lifts b)
    r, g, b = _patch(pending, profile.uv(profile.get("ld"), "START_COOP_UV"))
    assert abs(r - g) < 40 and abs(g - b) < 40                 # grey while waiting


# ---- tools/check_ld_profile.py: whole-window grabs ---------------------------------------

def _tool():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import check_ld_profile
    return check_ld_profile


def test_check_ld_profile_crops_window_grab_and_reports_chrome(capsys, tmp_path):
    import numpy as np
    ld = load_config(ROOT / "config" / "recorder_ld.toml")
    fx = load("ld_host_joined_start_ready")
    ch = ld.target.chrome
    pw, ph = ld.target.place[2:]
    grab = np.zeros((ph, pw, 3), np.uint8)          # black chrome around the content
    grab[ch.top:ch.top + fx.shape[0], ch.left:ch.left + fx.shape[1]] = fx
    p = tmp_path / "grab.png"
    cv2.imwrite(str(p), cv2.cvtColor(grab, cv2.COLOR_RGB2BGR))
    assert _tool().main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "L16 T80 R16 B8" in out and "content 1122x1994" in out
    assert "room=1" in out and "modalX=1" in out and "ready=1" in out


def test_check_ld_profile_reports_window_size_for_off_aspect():
    import numpy as np
    from types import SimpleNamespace as NS
    # AI-NOTE: a window narrower than left + 9:16 width cannot give 9:16 (fit_chrome clamps right
    # to 0); the tool must then name the window size that would.
    cfg = NS(target=NS(place=(0, 0, 500, 2082), chrome=NS(left=16, top=80, right=16, bottom=8)))
    _, line = _tool().content_of(np.zeros((2082, 500, 3), np.uint8), cfg)
    assert "NOT 9:16" in line and "window 1154x2082 would give 9:16" in line
