import numpy as np
import pytest

from rdom.perception import support


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "_DATA", str(tmp_path))
    monkeypatch.setattr(support, "_models", {})
    monkeypatch.setattr(support, "_warned_no_models", False)
    return tmp_path


def test_missing_type_model_warns_once(fresh, capsys):
    frame = np.zeros((1280, 720, 3), np.uint8)
    support.read_board_support(frame)
    support.read_cells_support(frame, [1, 2])
    out = capsys.readouterr().out
    assert out == f"support models not found in {fresh} -- every cell reads junk\n"


def test_existing_type_model_does_not_warn(fresh, capsys, monkeypatch):
    (fresh / support.TYPE_FILE).write_bytes(b"x")
    monkeypatch.setattr(support, "predict_types_support", lambda crops: (["junk"] * len(crops), [0.0] * len(crops)))
    support.read_board_support(np.zeros((1280, 720, 3), np.uint8))
    assert "support models not found" not in capsys.readouterr().out


@pytest.mark.parametrize("frame", [
    np.zeros((1280, 720), np.uint8),
    np.zeros((1280, 720, 4), np.uint8),
    np.zeros((1280, 720, 3), np.float32),
])
def test_detect_deck_odd_inputs_false(frame):
    assert support.detect_support_deck(frame) is False
