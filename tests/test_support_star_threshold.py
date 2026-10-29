import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from rdom.perception import gear, support

import support_gate as sg
import support_train_common as C


def patch_predictors(monkeypatch, p):
    monkeypatch.setattr(support, "predict_types_support", lambda crops: (["Growth"] * len(crops), [1.0] * len(crops)))
    monkeypatch.setattr(support, "predict_pips_support", lambda crops, src: [7] * len(crops))
    monkeypatch.setattr(support, "star_prob", lambda crops: np.full(len(crops), p))


def test_threshold_value():
    assert support.STAR_THRESHOLD == 0.7


@pytest.mark.parametrize("p, want", [(0.65, 6), (0.75, 7)])
def test_read_cells_support_star_threshold(monkeypatch, p, want):
    img = np.zeros((8, 8, 3), np.uint8)
    monkeypatch.setattr(gear, "cell_crops", lambda f: [img] * 15)
    monkeypatch.setattr(gear, "hires_cell", lambda f, c, n: img)
    patch_predictors(monkeypatch, p)
    assert support.read_cells_support(None, [1])[0]["pip"] == want


@pytest.mark.parametrize("p, want", [(0.65, 6), (0.75, 7)])
def test_gate_predict_star_threshold(monkeypatch, tmp_path, p, want):
    for f in support.STAR_FILES:
        (tmp_path / f).write_bytes(b"")
    monkeypatch.setattr(support, "_DATA", str(tmp_path))
    monkeypatch.setattr(C, "read_rgb", lambda path: np.zeros((8, 8, 3), np.uint8))
    patch_predictors(monkeypatch, p)
    _, pip = sg._predict("x", ["a"], ["Growth"], [7])
    assert pip[0] == want
