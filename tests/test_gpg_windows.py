"""rdT06: two Google Play Games windows; each profile's title regex finds exactly its own window."""
import os
import re

import pytest

from rdom import profile
from rdom.recorder import window
from rdom.recorder.config import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLES = {1: "랜덤 다이스 2 - CleanCardinal77", 2: "랜덤 다이스 2 - CumbersomeTutor145", 3: "Google Play Games"}


def target(name):
    return load_config(os.path.join(ROOT, profile.get(name).config)).target


class FakeUser32:
    def EnumWindows(self, cb, lparam):
        for hwnd in TITLES:
            cb(hwnd, lparam)

    def IsWindowVisible(self, hwnd):
        return True


@pytest.fixture
def fake_windows(monkeypatch):
    monkeypatch.setattr(window, "_user32", FakeUser32())
    monkeypatch.setattr(window, "_WNDENUMPROC", lambda f: f)
    monkeypatch.setattr(window, "window_title", lambda hwnd: TITLES[hwnd])


@pytest.mark.parametrize("name,hwnd", [("gpg", 1), ("gpg2", 2)])
def test_each_profile_regex_finds_only_its_own_window(fake_windows, name, hwnd):
    assert window.find_window(target(name).window_title_re) == hwnd


@pytest.mark.parametrize("name", ["gpg", "gpg2"])
def test_the_launcher_title_matches_neither_regex(name):
    assert not re.search(target(name).window_title_re, "Google Play Games")


def test_gpg2_window_is_placed_left_of_the_first_without_overlap_with_the_same_chrome():
    a, b = target("gpg"), target("gpg2")
    assert b.place == (1508, 2160, 1384, 2304)
    assert b.place[0] + b.place[2] < a.place[0]
    assert a.chrome == b.chrome
    assert (b.chrome.left, b.chrome.top, b.chrome.right, b.chrome.bottom) == (132, 72, 0, 0)
