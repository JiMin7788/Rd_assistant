import glob
import os

import cv2
import numpy as np
import pytest

from rdom.perception import invite

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "rdf04")
DATA = "C:/dev/rdom/data"
HOST = "대변먹는자"

POPUPS = ["gpg_invite_popup", "ld_invite_popup"]
LIVE = ["gpg_popup_225739", "gpg_popup_225741", "gpg_popup_225751",
        "gpg_popup_225753", "gpg_popup_225802", "gpg_popup_225814"]   # live GPG frames 2026-11-01 22:57
ROOMS = ["gpg_joined_room", "ld_host_pending", "ld_host_joined_start_ready"]
NON_POPUPS = ROOMS + ["gpg_host_invite_pending"]

# bounds read off the fixtures (both popups share these fractions)
ACCEPT_BTN = (0.21, 0.645, 0.78, 0.705)   # u0, v0, u1, v1 inside the yellow button
CLOSE_X = (0.835, 0.155, 0.90, 0.19)      # inside the red X banner


def load(name):
    im = cv2.imread(os.path.join(FIX, name + ".png"))
    assert im is not None, name
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def data_negatives():
    """Result screens + battle frames from the live data dir (read-only, by absolute path)."""
    ends = sorted(glob.glob(DATA + "/support_runs/*/end.png"))
    frames = sorted(glob.glob(DATA + "/support_frames/*/*.png"))
    out = ends + frames[::max(1, len(frames) // 20)]
    if len(out) < 10:
        pytest.skip("live data frames not available")
    return out


def inside(uv, box):
    return box[0] <= uv[0] <= box[2] and box[1] <= uv[1] <= box[3]


@pytest.mark.parametrize("name", POPUPS)
def test_popup_found_with_targets(name):
    p = invite.invite_popup(load(name))
    assert p is not None
    assert inside(p["accept_uv"], ACCEPT_BTN)
    assert inside(p["close_uv"], CLOSE_X)


@pytest.mark.parametrize("name", NON_POPUPS)
def test_popup_none_on_other_fixtures(name):
    assert invite.invite_popup(load(name)) is None


def test_popup_none_on_synthetic_and_data_frames():
    assert invite.invite_popup(np.zeros((2224, 1244, 3), np.uint8)) is None
    for p in data_negatives():
        f = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
        assert invite.invite_popup(f) is None, p


def test_invite_name_read():
    gpg = invite.invite_name(load("gpg_invite_popup"))
    assert gpg == HOST
    assert invite.name_matches(gpg, HOST)
    ld = invite.invite_name(load("ld_invite_popup"))
    assert ld == "배속봇"
    assert not invite.name_matches(ld, HOST)


@pytest.mark.parametrize("name", LIVE + ["gpg_invite_popup"])
def test_invite_name_matches_host_on_gpg_frames(name):
    ok, read = invite.invite_name_matches(load(name), HOST)
    assert ok, read


def test_invite_name_matches_ld_fixture_is_its_own_name():
    f = load("ld_invite_popup")
    assert invite.invite_name_matches(f, "배속봇")[0]
    assert not invite.invite_name_matches(f, HOST)[0]


@pytest.mark.parametrize("other", ["배속봇", "웅로어", "홍길동"])
@pytest.mark.parametrize("name", LIVE)
def test_invite_name_matches_declines_other_hosts(name, other):
    ok, read = invite.invite_name_matches(load(name), other)
    assert not ok, read


def test_name_matches():
    assert invite.name_matches("대변먹는자", HOST)
    assert invite.name_matches("대변 먹는자", HOST)
    assert not invite.name_matches("배속봇", HOST)
    assert not invite.name_matches("", HOST)
    assert invite.name_matches("대접번먹속중는자", HOST)   # OCR-interleaved with a badge, cover 1.0
    assert not invite.name_matches("대변먹", HOST)          # cover 0.6


@pytest.mark.parametrize("name", ROOMS)
def test_joined_room_true(name):
    assert invite.joined_room(load(name))


@pytest.mark.parametrize("name", POPUPS)
def test_joined_room_false_on_popups(name):
    assert not invite.joined_room(load(name))


def test_joined_room_false_on_result_and_battle():
    assert not invite.joined_room(np.zeros((2224, 1244, 3), np.uint8))
    for p in data_negatives():
        f = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
        assert not invite.joined_room(f), p
