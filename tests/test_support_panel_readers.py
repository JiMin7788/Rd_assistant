"""Power-panel readers (rdf03-t4): panel SP, buy-button price, card level. Synthetic frames, no data/."""
import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import digits, sp, support

ROOT = Path(__file__).resolve().parents[1]
H = 2224
W = round(H * 9 / 16)
GREEN = (60, 200, 120)                                   # RGB of the buy button; white digits sit on it


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def px(box):
    u0, v0, u1, v1 = box
    return int(u0 * W), int(v0 * H), int(u1 * W), int(v1 * H)


def abs_box(button, offsets):
    return (button[0] + offsets[0], button[1] + offsets[1], button[0] + offsets[2], button[1] + offsets[3])


def render(text, box, bg=(0, 0, 0)):
    """RGB crop of the box size: white `text` on `bg`."""
    x0, y0, x1, y1 = px(box)
    img = np.zeros((y1 - y0, x1 - x0, 3), np.uint8); img[:] = bg
    scale = 0.9 * img.shape[0] / 22
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 3, cv2.LINE_AA)
    return img


def frame_with(text, box, bg=(0, 0, 0)):
    f = np.zeros((H, W, 3), np.uint8)
    x0, y0, x1, y1 = px(box)
    f[y0:y1, x0:x1] = render(text, box, bg)
    return f


BTN = (0.4973, 0.9407)
BTN2 = (0.1296, 0.9407)


@pytest.fixture
def env(tmp_path, monkeypatch):
    tools = load("build_digit_templates")
    out = tmp_path / "tpl"; out.mkdir()
    specs = (("panelsp", sp.PANEL_SP_BOX, (0, 0, 0), ["12345", "67890", "480", "7080", "2961"]),
             ("price", abs_box(BTN, sp.PRICE_BOX), GREEN, ["250", "500", "134", "678", "90"]),
             ("powerlv", abs_box(BTN, support.LV_BOX), (0, 0, 0), ["1", "2", "3", "4", "5", "6", "7", "8", "9"]))
    for kind, box, bg, vals in specs:
        d = tmp_path / "data" / "digits" / kind; d.mkdir(parents=True)
        for i, v in enumerate(vals):
            cv2.imwrite(str(d / f"{v}_{i}.png"), cv2.cvtColor(render(v, box, bg), cv2.COLOR_RGB2BGR))
        tools.build_kind(kind, str(d), out=str(out))
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})
    return tmp_path / "data"


def test_boxes_are_four_floats():
    assert len(sp.PANEL_SP_BOX) == 4 and all(isinstance(x, float) for x in sp.PANEL_SP_BOX)
    assert all(0 <= x <= 1 for x in sp.PANEL_SP_BOX) and sp.PANEL_SP_BOX[0] < sp.PANEL_SP_BOX[2]
    assert len(sp.PRICE_BOX) == 4 and all(isinstance(x, float) for x in sp.PRICE_BOX)
    assert sp.PRICE_BOX[0] < sp.PRICE_BOX[2] and sp.PRICE_BOX[1] < sp.PRICE_BOX[3]
    assert sp.PRICE_BOX[0] < 0 < sp.PRICE_BOX[2]               # offsets around the button centre


@pytest.mark.parametrize("kind", ["panelsp", "price", "powerlv"])
def test_committed_templates_shape(kind):
    T = np.load(ROOT / "assets" / "templates" / f"digits_{kind}.npz")["T"]
    assert T.shape == (10, digits.GH, digits.GW)


def test_read_panel_sp_exact(env):
    assert sp.read_panel_sp(frame_with("7080", sp.PANEL_SP_BOX)) == 7080
    assert sp.read_panel_sp(frame_with("12345", sp.PANEL_SP_BOX)) == 12345


def test_read_price_exact_at_any_button(env):
    for btn in (BTN, BTN2):
        for text in ("250", "678"):
            assert sp.read_price(frame_with(text, abs_box(btn, sp.PRICE_BOX), GREEN), btn) == int(text)


def test_price_box_is_relative_to_the_button(env):
    """The same digits at the box of BTN must not be read when the caller names another button."""
    f = frame_with("250", abs_box(BTN, sp.PRICE_BOX), GREEN)
    assert sp.read_price(f, BTN) == 250
    assert sp.read_price(f, BTN2) is None
    assert sp.read_price(f, (BTN[0] + 0.001, BTN[1])) in (250, None)       # one px shift never gives another number


def test_ranges(env):
    assert sp.read_price(frame_with("0", abs_box(BTN, sp.PRICE_BOX), GREEN), BTN) is None     # price is 1..999_999
    assert sp.read_panel_sp(frame_with("0", sp.PANEL_SP_BOX)) in (0, None)


@pytest.mark.parametrize("make", [
    lambda: np.zeros((H, W), np.uint8),
    lambda: np.zeros((H, W, 3), np.uint8),
    lambda: np.full((H, W, 3), 255, np.uint8),
    lambda: np.random.default_rng(0).integers(0, 256, (H, W, 3), dtype=np.uint8),
    lambda: np.zeros((10, 10, 3), np.uint8),
    lambda: np.zeros((1, 1, 3), np.uint8),
    lambda: None,
])
def test_odd_frames_give_none(env, make):
    f = make()
    assert sp.read_panel_sp(f) is None and sp.read_price(f, BTN) is None


@pytest.mark.parametrize("button", [None, (), (0.5,), "ab", (float("nan"), 0.9), (0.5, float("inf")), (-1.0, -1.0),
                                    (5.0, 5.0), (0.5, 3.0), ("x", "y"), (0.0, 0.0)])
def test_odd_buttons_give_none(env, button):
    f = frame_with("250", abs_box(BTN, sp.PRICE_BOX), GREEN)
    assert sp.read_price(f, button) is None


def test_popup_over_digits_gives_none(env):
    f = frame_with("7080", sp.PANEL_SP_BOX)
    x0, y0, x1, y1 = px(sp.PANEL_SP_BOX)
    cv2.putText(f, "+30", (x0 + 30, y1), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 6)
    assert sp.read_panel_sp(f) in (None, 7080)                 # exact or nothing, never another value


def test_missing_npz_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(digits, "_TPL", str(tmp_path))
    monkeypatch.setattr(digits, "_cache", {})
    assert sp.read_panel_sp(frame_with("7080", sp.PANEL_SP_BOX)) is None
    assert sp.read_price(frame_with("250", abs_box(BTN, sp.PRICE_BOX), GREEN), BTN) is None


def test_card_level_on_powerlv_templates(env):
    f = frame_with("7", abs_box(BTN, support.LV_BOX))
    assert support.card_level(f, BTN) == 7


def test_check_lines(env):
    cs = load("check_support_assets")
    for kind, box, bg, good in (("panelsp", sp.PANEL_SP_BOX, (0, 0, 0), "7080"),
                                ("price", abs_box(cs.PANEL_BUTTON, sp.PRICE_BOX), GREEN, "250"),
                                ("powerlv", abs_box(cs.PANEL_BUTTON, support.LV_BOX), (0, 0, 0), "7")):
        d = env / "digits" / kind
        for f in d.glob("*.png"):
            f.unlink()
        img = lambda t: cv2.cvtColor(render(t, box, bg), cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(d / f"{good}_a.png"), img(good))                                  # correct
        cv2.imwrite(str(d / f"{int(good) + 1}_b.png"), img(good))                         # label differs: wrong
        cv2.imwrite(str(d / f"{good}_c.png"), np.full_like(img(good), 255))              # unreadable: none
        cv2.imwrite(str(d / "x_d.png"), img(good))                                        # no value: skipped
        cv2.imwrite(str(d / "7_e.png"), np.zeros((5, 5), np.uint8))                       # other size: skipped
    assert cs.check_panel_sp(str(env)) == "panel sp: n=3 correct=1 none=1 wrong=1"
    assert cs.check_price(str(env)) == "price: n=3 correct=1 none=1 wrong=1"
    assert cs.check_power_level(str(env)) == "power level: n=3 correct=1 none=1 wrong=1"


def test_main_prints_three_new_lines_after_t3_lines(env, tmp_path, capsys):
    cs = load("check_support_assets")
    assert cs.main(["--data-dir", str(env), "--out-dir", str(tmp_path / "o")]) == 0
    lines = capsys.readouterr().out.splitlines()
    heads = ["score: n=", "score lobby: none=", "deck bar: support", "deck bar excluded: ", "power cards: ", "lv box: drew",
             "sp: n=", "summon cost: n=", "panel sp: n=", "price: n=", "power level: n="]
    assert len(lines) == len(heads)
    assert all(l.startswith(h) for l, h in zip(lines, heads))
