import importlib.util
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import digits, score
from rdom.perception.score import ScoreTracker, read_score

H = 1280
W = round(H * 9 / 16)
REAL_BOX = score.SCORE_BOX                      # the committed box, before any monkeypatching
BOX = (0.30, 0.02, 0.70, 0.08)
BOX_PX = (int(BOX[0] * W), int(BOX[1] * H), int(BOX[2] * W), int(BOX[3] * H))


def render_crop(text):
    """White digits on dark, the size of the score box."""
    x0, y0, x1, y1 = BOX_PX
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 3, cv2.LINE_AA)
    return img


def frame_with(crop):
    x0, y0, x1, y1 = BOX_PX
    f = np.zeros((H, W, 3), np.uint8)
    f[y0:y1, x0:x1] = crop[..., None]
    return f


def load_build_tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "build_digit_templates.py"
    spec = importlib.util.spec_from_file_location("build_digit_templates", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_crops(src, numbers):
    src.mkdir(parents=True)
    for i, n in enumerate(numbers):
        cv2.imwrite(str(src / f"{n}_{i}.png"), render_crop(n))


@pytest.fixture
def tools():
    return load_build_tool()


@pytest.fixture
def templates(tmp_path, tools, monkeypatch):
    src = tmp_path / "data" / "digits" / "score"
    make_crops(src, ["61937", "40528"])          # covers all ten digits, none of the test numbers
    out = tmp_path / "tpl"
    out.mkdir()
    assert tools.build_kind("score", str(src), out=str(out)) == []
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})
    monkeypatch.setattr(score, "SCORE_BOX", BOX)
    return out


def test_box_is_bounded_float_4tuple():
    b = score.SCORE_BOX
    assert isinstance(b, tuple) and len(b) == 4 and all(isinstance(x, float) for x in b)
    u0, v0, u1, v1 = b
    assert 0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1


def test_none_without_box(monkeypatch):
    monkeypatch.setattr(score, "SCORE_BOX", None)
    assert read_score(np.zeros((H, W, 3), np.uint8)) is None


def real_frame(text):
    u0, v0, u1, v1 = REAL_BOX
    x0, y0, x1, y1 = int(u0 * W), int(v0 * H), int(u1 * W), int(v1 * H)
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 3, cv2.LINE_AA)
    f = np.zeros((H, W, 3), np.uint8)
    f[y0:y1, x0:x1] = img[..., None]
    return f


def test_real_box_synthetic_thousands_separator_never_wrong(templates, monkeypatch):
    monkeypatch.setattr(score, "SCORE_BOX", REAL_BOX)
    assert read_score(real_frame("2,000")) in (2000, None)


@pytest.mark.parametrize("name", ["black", "white", "noise", "tiny", "grey2d"])
def test_real_box_degenerate_inputs_none(templates, monkeypatch, name):
    monkeypatch.setattr(score, "SCORE_BOX", REAL_BOX)
    rng = np.random.default_rng(0)
    frames = {"black": np.zeros((H, W, 3), np.uint8), "white": np.full((H, W, 3), 255, np.uint8),
              "noise": rng.integers(0, 256, (H, W, 3), dtype=np.uint8),
              "tiny": np.zeros((10, 10, 3), np.uint8), "grey2d": np.full((H, W), 128, np.uint8)}
    assert read_score(frames[name]) is None


def test_missing_templates_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(digits, "_TPL", str(tmp_path))
    monkeypatch.setattr(digits, "_cache", {})
    monkeypatch.setattr(score, "SCORE_BOX", BOX)
    assert read_score(frame_with(render_crop("1820"))) is None


@pytest.mark.parametrize("n", ["1820", "30475"])
def test_reads_synthetic_score(templates, n):
    assert read_score(frame_with(render_crop(n))) == int(n)


def test_reads_frame_wider_than_content(templates):
    f = frame_with(render_crop("1820"))
    wide = np.zeros((H, W + 100, 3), np.uint8)
    wide[:, :W] = f
    assert read_score(wide) == 1820


def test_covered_digits_refused(templates):
    crop = render_crop("30475")
    crop[:, crop.shape[1] // 2:] = 255            # filled rectangle over the right half
    assert read_score(frame_with(crop)) is None


@pytest.mark.parametrize("fill", [255, 0])
@pytest.mark.parametrize("frac", [0.15, 0.30, 0.50])
@pytest.mark.parametrize("n", ["61937", "40528"])
def test_effect_icon_over_first_digit_reads_true_value_or_none(templates, n, frac, fill):
    """A bright (or dark) icon block over the top part of the first digit: the true number or None, never another number."""
    crop = render_crop(n)
    ys, xs = np.where(crop > 0)
    top, bottom, left = ys.min(), ys.max(), xs.min()
    crop[:top + int(frac * (bottom - top)), :left + (xs.max() - left) // (2 * len(n)) * 3] = fill
    assert read_score(frame_with(crop)) in (int(n), None)


@pytest.mark.parametrize("shape", [(0,), (0, 0), (0, 5, 3), (5, 0, 3), (1,), (7,), (10, 10), (10, 10, 3)])
def test_degenerate_shapes_never_raise(shape):
    """np.array([]) is 1-D: slicing it as a frame used to raise IndexError."""
    assert read_score(np.zeros(shape, np.uint8)) is None


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def real_crop_frame(name):
    """Full frame (2224 high, like the H1 captures) with a real score-box crop in place; committed digits_score.npz is used."""
    crop = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)
    h = 2224; w = round(h * 9 / 16)
    u0, v0, _, _ = REAL_BOX
    x0, y0 = int(u0 * w), int(v0 * h)
    f = np.zeros((h, w, 3), np.uint8)
    f[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    return f


@pytest.mark.parametrize("name, true", [("score_s4_2667_read667.png", 2667), ("score_s4_2667_read2367.png", 2667),
                                        ("score_s4_4980_read1980.png", 4980), ("score_s4_4980_read4910.png", 4980)])
def test_qa_s4_painted_real_crops_true_or_none(name, true):
    """QA S4 frames: a flat shape painted over some digits (first digit gone / cut 6 / cut 4 / cut 8) used to read as 667, 2367, 1980, 4910."""
    assert read_score(real_crop_frame(name)) in (true, None)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("part", [0.4, 0.55, 0.7])
@pytest.mark.parametrize("idx", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("n", ["61937", "40528"])
def test_flat_shape_over_part_of_one_digit_true_or_none(templates, n, idx, part, side):
    """Paint the left/right 40-70 % of one digit over its full height (also middle digits): the true number or None."""
    crop = render_crop(n)
    xs = np.where(crop.max(0) > 0)[0]
    pitch = (xs.max() - xs.min()) / len(n)
    x0 = xs.min() + idx * pitch
    a, b = (x0, x0 + part * pitch) if side == "left" else (x0 + (1 - part) * pitch, x0 + pitch)
    crop[:, int(a):int(b)] = 255 if idx % 2 else 0
    assert read_score(frame_with(crop)) in (int(n), None)


def test_layout_ok_accepts_even_centred_row_and_refuses_irregular_ones():
    even = [(100, 0, 99), (226, 0, 99), (352, 1, 100), (478, 0, 99)]
    assert score.layout_ok(even, 578, 120)
    assert not score.layout_ok([(190, 17, 99)] + even[1:], 578, 120)       # first glyph is a cut piece off the pitch
    assert not score.layout_ok([(100, 9, 99)] + even[1:], 578, 120)        # top cut away
    assert not score.layout_ok([(x + 150, a, b) for x, a, b in even[:3]], 578, 120)   # first digit missing: run off centre


def test_tracker_confirms_after_two_equal_reads():
    t = ScoreTracker()
    assert t.update(1500) is None and t.value is None
    assert t.update(1500) == 1500 and t.value == 1500


def test_tracker_none_in_between_keeps_pending():
    t = ScoreTracker()
    assert t.update(1500) is None
    assert t.update(None) is None
    assert t.update(1500) == 1500 and t.value == 1500


def test_tracker_never_confirms_negative_or_above_99999():
    t = ScoreTracker()
    assert t.update(-5) is None and t.update(-5) is None and t.value is None
    assert t.update(100000) is None and t.update(100000) is None and t.value is None


def test_tracker_ignores_lower_than_confirmed():
    t = ScoreTracker()
    t.update(4000); t.update(4000)
    assert t.update(100) is None and t.update(100) is None
    assert t.value == 4000
    assert t.update(4100) is None and t.update(4100) == 4100 and t.value == 4100


def test_tracker_lower_read_keeps_pending():
    t = ScoreTracker()
    t.update(4000); t.update(4000)
    assert t.update(4100) is None
    assert t.update(100) is None                      # ignored like a failed read: pending 4100 stays
    assert t.update(4100) == 4100
    t2 = ScoreTracker()
    t2.update(4000); t2.update(4000); t2.update(4100)
    t2.update(100); t2.update(4200)                   # 4100 and 4200 are not consecutive equals
    assert t2.value == 4000


def test_tracker_new_value_needs_two_reads():
    t = ScoreTracker()
    t.update(1500); t.update(1500)
    assert t.update(1600) is None
    assert t.value == 1500
    assert t.update(1600) == 1600 and t.value == 1600


@pytest.mark.parametrize("kind", ["score", "powerlv"])
def test_build_kind_any_name(tmp_path, tools, kind):
    src = tmp_path / kind
    make_crops(src, ["61937", "40528"])
    out = tmp_path / "out"
    out.mkdir()
    assert tools.build_kind(kind, str(src), out=str(out)) == []
    T = np.load(out / f"digits_{kind}.npz")["T"]
    assert T.shape == (10, digits.GH, digits.GW)


def test_build_kind_fallback_for_missing_digits(tmp_path, tools):
    src = tmp_path / "score"
    make_crops(src, ["6193"])
    out = tmp_path / "out"
    out.mkdir()
    fb = np.full((10, digits.GH, digits.GW), 0.5, np.float32)
    assert tools.build_kind("score", str(src), out=str(out), fallback=fb) == [0, 2, 4, 5, 7, 8]
    T = np.load(out / "digits_score.npz")["T"]
    assert np.allclose(T[0], 0.5) and not np.allclose(T[6], 0.5)
