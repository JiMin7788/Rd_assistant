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
    assert lines[-2].startswith("sp: n=") and lines[-1].startswith("summon cost: n=")
    assert lines[0].startswith("score: n=")


def test_dryrun_prints_sp_and_cost(monkeypatch):
    tool = load("support_dryrun")
    monkeypatch.setattr(tool, "read_sp", lambda f: 50630)
    monkeypatch.setattr(tool, "read_summon_cost", lambda f: None)
    monkeypatch.setattr(tool, "read_board_support", lambda f: [{"cell": i + 1, "type": "junk", "pip": 0} for i in range(15)])
    lines = tool.dryrun(np.zeros((H, W, 3), np.uint8))
    assert lines[-2:] == ["sp: 50630", "summon cost: None"]
