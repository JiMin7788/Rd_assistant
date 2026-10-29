import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import board, gear, support

ROOT = Path(__file__).resolve().parents[1]
H = 1280
W = round(H * 9 / 16)
BAR = (450, 1200)            # top-left of the deck-bar patch, inside DECK_BAR_BOX
CARD = 24                    # card patch side
CARD_Y = 1050                # inside POWER_BAND


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def noise(h, w, seed):
    return np.random.RandomState(seed).randint(0, 256, (h, w, 3)).astype(np.uint8)


def save_rgb(path, img):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))


BAR_PATCH = noise(30, 60, 1)
CARDS = {"ui_power_growth_card.png": noise(CARD, CARD, 2),
         "ui_power_align_card_a.png": noise(CARD, CARD, 3),
         "ui_power_res_card.png": noise(CARD, CARD, 4)}


def frame(seed, bar=False, battle=True, panel=False, cards=()):
    """Noise frame; pixel (0,0) marks is_battle, pixel (0,1) marks an open power panel.
    cards: (template file, u) pairs pasted centred at u."""
    f = noise(H, W, 100 + seed)
    f[0, 0, 0] = 7 if battle else 1
    f[0, 1, 0] = 7 if panel else 1
    if bar:
        f[BAR[1]:BAR[1] + 30, BAR[0]:BAR[0] + 60] = BAR_PATCH
    for fn, u in cards:
        x = round(u * W) - CARD // 2
        f[CARD_Y:CARD_Y + CARD, x:x + CARD] = CARDS[fn]
    return f


@pytest.fixture
def env(tmp_path, monkeypatch):
    tpl = tmp_path / "tpl"
    tpl.mkdir()
    save_rgb(tpl / "deck_support.png", BAR_PATCH)
    for fn, img in CARDS.items():
        save_rgb(tpl / fn, img)
    monkeypatch.setattr(support, "_TPL", str(tpl))
    monkeypatch.setattr(support, "_models", {})
    monkeypatch.setattr(board, "is_battle", lambda f: int(f[0, 0, 0]) == 7)
    monkeypatch.setattr(gear, "ui_state", lambda f: {"power_panel": int(f[0, 1, 0]) == 7})
    monkeypatch.setattr(gear, "power_buttons", lambda f: [(0.2, 0.94), (0.5, 0.94), (0.8, 0.94)])
    return load("check_support_assets"), tmp_path / "data" / "support_frames"


def test_deck_bar_counts_and_excludes(env):
    cs, sf = env
    save_rgb(sf / "sup1" / "1.0.png", frame(1, bar=True))
    save_rgb(sf / "sup1" / "2.0.png", frame(2, bar=True))
    save_rgb(sf / "sup1" / "3.0.png", frame(3))                              # counted, bar not found
    save_rgb(sf / "sup1" / "4.0.png", frame(4, bar=True, panel=True))        # excluded: panel
    save_rgb(sf / "sup1" / "5.0.png", frame(5, battle=False))                # excluded: bar hidden
    save_rgb(sf / "sup1" / "panel_6.0.png", frame(6, panel=True))            # not a battle frame name: ignored
    save_rgb(sf / "manual" / "g1.png", frame(7))                             # gear: must be False
    save_rgb(sf / "manual" / "g2.png", frame(8))
    save_rgb(sf / "manual" / "g3.png", frame(9, bar=True))                   # gear frame matching the template: not False
    save_rgb(sf / "manual" / "lobby.png", frame(10, battle=False))           # not a battle frame: not in m
    out = cs.check_deck_bar(str(sf.parent)).splitlines()
    assert out == ["deck bar: support 2/3 gear-false 2/3",
                   "deck bar excluded: 2 (sup1/4.0.png: panel, sup1/5.0.png: bar hidden)"]


def test_deck_bar_excluded_lists_at_most_ten_names(env):
    cs, sf = env
    for i in range(12):
        save_rgb(sf / "sup1" / f"{i}.0.png", frame(i, panel=True))
    line = cs.check_deck_bar(str(sf.parent)).splitlines()[1]
    assert line.startswith("deck bar excluded: 12 (") and line.endswith(", ...)")
    assert line.count(": panel") == 10


def test_deck_bar_without_frames(env):
    cs, sf = env
    assert cs.check_deck_bar(str(sf.parent)).splitlines() == ["deck bar: support 0/0 gear-false 0/0", "deck bar excluded: 0"]


def test_power_cards_counts_complete_panels(env):
    cs, sf = env
    full = [("ui_power_res_card.png", 0.2), ("ui_power_align_card_a.png", 0.5), ("ui_power_growth_card.png", 0.8)]
    save_rgb(sf / "sup1" / "panel_1.0.png", frame(1, cards=full))
    save_rgb(sf / "sup2" / "panel_2.0.png", frame(2, cards=full[:2]))        # Growth missing
    save_rgb(sf / "sup3" / "panel_3.0.png", frame(3, cards=[               # Alignment and Growth on one button
        ("ui_power_align_card_a.png", 0.2), ("ui_power_growth_card.png", 0.24), ("ui_power_res_card.png", 0.5)]))
    save_rgb(sf / "sup3" / "9.0.png", frame(4, cards=full))                  # not a panel frame
    assert cs.check_power_cards(str(sf.parent)) == "power cards: 1/3"


def test_power_cards_without_frames(env):
    cs, sf = env
    assert cs.check_power_cards(str(sf.parent)) == "power cards: 0/0"


def test_draw_lv_boxes_writes_overlays(env, tmp_path, monkeypatch):
    cs, sf = env
    monkeypatch.setattr(support, "LV_BOX", (0.02, -0.04, 0.05, -0.02))
    save_rgb(sf / "sup1" / "panel_1.5.png", frame(1))
    save_rgb(sf / "sup2" / "panel_2.5.png", frame(2))
    save_rgb(sf / "sup2" / "7.0.png", frame(3))
    out = tmp_path / "ov"
    assert cs.draw_lv_boxes(str(sf.parent), str(out)) == f"lv box: drew 2 overlays to {out}"
    assert sorted(p.name for p in out.iterdir()) == ["lvbox_sup1_panel_1.5.png", "lvbox_sup2_panel_2.5.png"]
    im = cv2.imread(str(out / "lvbox_sup1_panel_1.5.png"))
    assert im.shape == (H, W, 3)
    assert (im[..., 2] != cv2.imread(str(sf / "sup1" / "panel_1.5.png"))[..., 2]).any()      # a box was drawn


def test_draw_lv_boxes_without_box_draws_nothing(env, tmp_path, monkeypatch):
    cs, sf = env
    monkeypatch.setattr(support, "LV_BOX", None)
    save_rgb(sf / "sup1" / "panel_1.5.png", frame(1))
    out = tmp_path / "ov"
    assert cs.draw_lv_boxes(str(sf.parent), str(out)) == f"lv box: drew 0 overlays to {out}"
    assert not out.exists()


@pytest.mark.parametrize("fn", ["deck_support.png", "ui_power_growth_card.png", "ui_power_align_card_a.png",
                                "ui_power_res_card.png"])
def test_committed_templates_exist(fn):
    p = ROOT / "assets" / "templates" / fn
    assert p.is_file() and p.stat().st_size > 0
    assert cv2.imread(str(p)) is not None


def test_lv_box_is_four_floats():
    assert isinstance(support.LV_BOX, tuple) and len(support.LV_BOX) == 4
    assert all(isinstance(v, float) for v in support.LV_BOX)
    du0, dv0, du1, dv1 = support.LV_BOX
    assert du0 < du1 and dv0 < dv1
