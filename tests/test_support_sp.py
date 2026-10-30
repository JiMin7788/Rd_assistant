import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import digits, sp

ROOT = Path(__file__).resolve().parents[1]
H = 2224
W = round(H * 9 / 16)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def box_px(box, h=H):
    w = round(h * 9 / 16); u0, v0, u1, v1 = box
    return int(u0 * w), int(v0 * h), int(u1 * w), int(v1 * h)


def render(text, box):
    x0, y0, x1, y1 = box_px(box)
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    scale = 0.9 * img.shape[0] / 22
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, scale, 255, 3, cv2.LINE_AA)
    return img


def frame_with(text, box):
    f = np.zeros((H, W, 3), np.uint8)
    x0, y0, x1, y1 = box_px(box)
    f[y0:y1, x0:x1] = render(text, box)[..., None]
    return f


@pytest.fixture
def env(tmp_path, monkeypatch):
    tools = load("build_digit_templates")
    out = tmp_path / "tpl"; out.mkdir()
    for kind, box, vals in (("sp", sp.SP_BOX, ["12345", "67890", "480", "7080", "2961"]),
                            ("cost", sp.COST_BOX, ["1234", "5678", "90", "480", "1420"])):
        d = tmp_path / "data" / "digits" / kind; d.mkdir(parents=True)
        for i, v in enumerate(vals):
            cv2.imwrite(str(d / f"{v}_{i}.png"), render(v, box))
        tools.build_kind(kind, str(d), out=str(out))
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})
    return tmp_path / "data"


@pytest.mark.parametrize("box", [sp.SP_BOX, sp.COST_BOX])
def test_boxes_are_four_floats_in_unit_range(box):
    assert len(box) == 4 and all(isinstance(x, float) and 0 <= x <= 1 for x in box)
    assert box[0] < box[2] and box[1] < box[3]


@pytest.mark.parametrize("kind", ["sp", "cost"])
def test_committed_templates_shape(kind):
    T = np.load(ROOT / "assets" / "templates" / f"digits_{kind}.npz")["T"]
    assert T.shape == (10, digits.GH, digits.GW)


def test_reads_exact(env):
    assert sp.read_sp(frame_with("7080", sp.SP_BOX)) == 7080
    assert sp.read_summon_cost(frame_with("1420", sp.COST_BOX)) == 1420


def test_ranges(env):
    assert sp.read_sp(frame_with("0", sp.SP_BOX)) in (0, None)
    assert sp.read_summon_cost(frame_with("0", sp.COST_BOX)) is None       # cost is 1..99_999


@pytest.mark.parametrize("make", [
    lambda: np.zeros((H, W), np.uint8),                                     # 2-D grey
    lambda: np.zeros((H, W, 3), np.uint8),
    lambda: np.full((H, W, 3), 255, np.uint8),
    lambda: np.random.default_rng(0).integers(0, 256, (H, W, 3), dtype=np.uint8),
    lambda: np.zeros((10, 10, 3), np.uint8),
    lambda: np.zeros((1, 1, 3), np.uint8),
])
def test_odd_inputs_give_none(env, make):
    f = make()
    assert sp.read_sp(f) is None and sp.read_summon_cost(f) is None


def test_missing_npz_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(digits, "_TPL", str(tmp_path))
    monkeypatch.setattr(digits, "_cache", {})
    assert sp.read_sp(frame_with("7080", sp.SP_BOX)) is None
    assert sp.read_summon_cost(frame_with("480", sp.COST_BOX)) is None


def test_read_crop_degenerate(env):
    assert sp.read_crop(np.zeros((0, 5), np.uint8), "sp") is None
    assert sp.read_crop(np.zeros((3, 3), np.uint8), "cost") is None
    assert sp.read_crop(np.zeros((20, 20, 3), np.uint8), "sp") is None
    assert sp.read_crop(render("2961", sp.SP_BOX), "sp") == 2961


def test_check_lines(env):
    cs = load("check_support_assets")
    for kind, box in (("sp", sp.SP_BOX), ("cost", sp.COST_BOX)):
        d = env / "digits" / kind
        cv2.imwrite(str(d / "7080_a.png") if kind == "sp" else str(d / "480_a.png"),
                    render("7080" if kind == "sp" else "480", box))                          # correct
        cv2.imwrite(str(d / "7081_b.png") if kind == "sp" else str(d / "481_b.png"),
                    render("7080" if kind == "sp" else "480", box))                          # label differs: wrong
        cv2.imwrite(str(d / "7080_c.png") if kind == "sp" else str(d / "480_c.png"),
                    np.full_like(render("1", box), 255))                                     # unreadable: none
        cv2.imwrite(str(d / "x_d.png"), render("1", box))                                    # no value: skipped
        cv2.imwrite(str(d / "7_e.png"), np.zeros((5, 5), np.uint8))                          # other box size: skipped
    assert cs.check_sp(str(env)) == "sp: n=8 correct=6 none=1 wrong=1"
    assert cs.check_summon_cost(str(env)) == "summon cost: n=8 correct=6 none=1 wrong=1"


def test_main_prints_new_lines_last(env, tmp_path, capsys):
    cs = load("check_support_assets")
    assert cs.main(["--data-dir", str(env), "--out-dir", str(tmp_path / "o")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-5].startswith("sp: n=") and lines[-4].startswith("summon cost: n=")      # rdf03-t4 adds three lines after
    assert lines[0].startswith("score: n=")


def test_dryrun_prints_sp_and_cost(monkeypatch):
    tool = load("support_dryrun")
    monkeypatch.setattr(tool, "read_sp", lambda f: 50630)
    monkeypatch.setattr(tool, "read_summon_cost", lambda f: None)
    monkeypatch.setattr(tool, "read_board_support", lambda f: [{"cell": i + 1, "type": "junk", "pip": 0} for i in range(15)])
    lines = tool.dryrun(np.zeros((H, W, 3), np.uint8))
    assert lines[-2:] == ["sp: 50630", "summon cost: None"]


def test_dimmed_frame_reads_sp_and_cost(env):
    # AI-NOTE: S18 -- a dice-info panel dims the battle, the white digits peak at ~70; reading used to give None
    for text, box, read, want in (("7080", sp.SP_BOX, sp.read_sp, 7080), ("1420", sp.COST_BOX, sp.read_summon_cost, 1420)):
        dim = (frame_with(text, box) * (70 / 255)).astype(np.uint8)
        assert read(dim) == want


def test_near_black_crop_is_not_amplified(env):
    assert sp.read_sp((frame_with("7080", sp.SP_BOX) * (20 / 255)).astype(np.uint8)) is None


# --- rdf03-r3-s16: a number wider than the box must read None, not its visible left part ---------------------------------

PRICE_UV = (0.5, 0.9)


def price_box(uv=PRICE_UV):
    du0, dv0, du1, dv1 = sp.PRICE_BOX
    return (uv[0] + du0, uv[1] + dv0, uv[0] + du1, uv[1] + dv1)


@pytest.fixture
def env4(tmp_path, monkeypatch):
    """Templates for sp, cost, panelsp and price, drawn with spaced_frame (n digits per box) so they match the test strips."""
    tools = load("build_digit_templates")
    out = tmp_path / "tpl"; out.mkdir()
    for kind, box, n in (("sp", sp.SP_BOX, 6), ("cost", sp.COST_BOX, 5), ("panelsp", sp.PANEL_SP_BOX, 5), ("price", price_box(), 3)):
        d = tmp_path / "data" / "digits" / kind; d.mkdir(parents=True)
        x0, y0, x1, y1 = box_px(box)
        for i in range(0, 10, n):
            v = "1234567890"[i:i + n]
            cv2.imwrite(str(d / f"{v}_{i}.png"), spaced_frame(v, box, n)[y0:y1, x0:x1])
        tools.build_kind(kind, str(d), out=str(out))
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})


def spaced_frame(text, box, n_fit, right_fill=None):
    """Digits at a fixed pitch of (box width / n_fit) from the box's left edge, so digit n_fit+1 lies wholly right of the
    box with the box's last column in a gap (a real number longer than the box, not a clipped glyph)."""
    f = np.zeros((H, W, 3), np.uint8)
    x0, y0, x1, y1 = box_px(box)
    pitch = (x1 - x0) / n_fit
    scale = 0.45 * (y1 - y0) / 22
    for i, ch in enumerate(text):
        (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        cv2.putText(f, ch, (int(x0 + i * pitch + (pitch - tw) / 2), (y0 + y1 + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    if right_fill is not None:                                   # light sand right of the pill, as on a real battle frame
        f[y0 - 20:y1 + 20, x1 + 3:] = right_fill
    return f


CASES = [
    ("sp", lambda f: sp.read_sp(f), sp.SP_BOX, 6, [("123456", 123456), ("1234567", None), ("9999999", None), ("10000000", None)]),
    ("cost", lambda f: sp.read_summon_cost(f), sp.COST_BOX, 5, [("12345", 12345), ("100000", None), ("123456", None)]),
    ("panelsp", lambda f: sp.read_panel_sp(f), sp.PANEL_SP_BOX, 5, [("12345", 12345), ("123456", None), ("10000000", None)]),
    ("price", lambda f: sp.read_price(f, PRICE_UV), price_box(), 3, [("250", 250), ("2500", None), ("5200", None), ("2500000", None)]),
]
PARAMS = [(k, rd, box, n, t, want) for k, rd, box, n, ts in CASES for t, want in ts]


@pytest.mark.parametrize("kind,read,box,n_fit,text,want", PARAMS)
def test_number_wider_than_box_is_none(env4, kind, read, box, n_fit, text, want):
    assert read(spaced_frame(text, box, n_fit)) == want


@pytest.mark.parametrize("kind,read,box,n_fit,text,want", [p for p in PARAMS if p[5] is not None])
def test_light_background_right_of_box_keeps_fitting_reads(env4, kind, read, box, n_fit, text, want):
    # AI-NOTE: the overflow strip lies on sand (grey ~205) behind/after the pill; that is no digit and must not turn a fitting number into None
    assert read(spaced_frame(text, box, n_fit, right_fill=205)) == want


def test_beige_blob_right_of_pill_is_no_digit(env4):
    # AI-NOTE: real frames show sand / skin (R215 G170 B130) covering only part of the strip height beside the pill end; its grey is > 170 but its weakest channel is not
    f = spaced_frame("123456", sp.SP_BOX, 6)
    x0, y0, x1, y1 = box_px(sp.SP_BOX)
    f[y0 + 12:y1 + 20, x1 + 3:] = (215, 170, 130)
    assert sp.read_sp(f) == 123456


def test_dimmed_wide_number_is_none(env4):
    f = (spaced_frame("1234567", sp.SP_BOX, 6) * (70 / 255)).astype(np.uint8)
    assert sp.read_sp(f) is None
    assert sp.read_sp((spaced_frame("123456", sp.SP_BOX, 6) * (70 / 255)).astype(np.uint8)) == 123456


def test_zero_price_is_none(env4):
    assert sp.read_price(spaced_frame("0", price_box(), 3), PRICE_UV) is None


# --- rdf03-r4-s17: price at the support.power_cards uv (about 3 px left of the button centre) ----------------------------

def test_one_column_of_the_last_digit_in_the_strip_is_no_overflow():
    # AI-NOTE: S17 -- at power_cards' uv the box edge cut the last '0' of 250 and its final column (1 px wide, 16 of 34 px high)
    # lay in the overflow strip, so read_price gave None; a real next digit is far wider
    strip = np.zeros((34, 28), np.uint8)
    strip[10:26, 0] = 255
    assert not sp._digits_beyond(strip)
    strip[10:26, :8] = 255
    assert sp._digits_beyond(strip)


PANEL_141449 = "C:/dev/rdom/data/support_frames/sup20261029_141449/panel_121.3.png"


@pytest.mark.skipif(not Path(PANEL_141449).exists(), reason="saved panel frame not on this machine")
def test_price_at_power_cards_uv_on_saved_panel():
    from rdom.perception import support
    im = cv2.cvtColor(cv2.imread(PANEL_141449), cv2.COLOR_BGR2RGB)
    cards = support.power_cards(im)
    assert [sp.read_price(im, uv) for uv in cards.values()] == [250, 250, 250]
