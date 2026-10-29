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
