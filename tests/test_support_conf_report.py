import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from rdom.perception import gear, support

import support_conf_report as cr
import support_train_common as C

# ---- read_cells_support ----

TYPES = ["Resonance", "Alignment", "empty", "Bubble", "junk"]


@pytest.fixture
def fakes(monkeypatch):
    """Content-based fakes: cell k's crop is filled with k, so a result cannot depend on the batch position."""
    monkeypatch.setattr(gear, "cell_crops", lambda f: [np.full((4, 4, 3), k, np.uint8) for k in range(1, 16)])
    monkeypatch.setattr(gear, "hires_cell", lambda f, cell, size=128: np.full((4, 4, 3), cell, np.uint8))
    monkeypatch.setattr(support, "predict_types_support",
                        lambda cr_: ([TYPES[int(c[0, 0, 0]) % 5] for c in cr_], [int(c[0, 0, 0]) / 20 for c in cr_]))
    monkeypatch.setattr(support, "predict_pips_support",
                        lambda cr_, src="auto": [int(c[0, 0, 0]) % 7 + 1 if src == "auto" else 2 for c in cr_])
    return monkeypatch


@pytest.mark.parametrize("src", ["auto", "gear"])
@pytest.mark.parametrize("star", [True, False])
def test_cells_equal_board_entries_in_given_order(fakes, src, star):
    fakes.setattr(support, "star_prob",
                  (lambda hr: np.array([0.9 if int(c[0, 0, 0]) % 2 else 0.1 for c in hr])) if star else (lambda hr: None))
    frame = np.zeros((10, 10, 3), np.uint8)
    board = support.read_board_support(frame, src)
    assert [d["cell"] for d in board] == list(range(1, 16))
    cells = [9, 1, 14, 4, 6, 15]
    got = support.read_cells_support(frame, cells, src)
    assert got == [board[c - 1] for c in cells]
    assert support.read_cells_support(frame, [], src) == []


def test_star_applies_per_cell_in_auto(fakes):
    fakes.setattr(support, "predict_pips_support", lambda cr_, src="auto": [7] * len(cr_))
    fakes.setattr(support, "star_prob", lambda hr: np.array([0.9 if int(c[0, 0, 0]) == 1 else 0.1 for c in hr]))
    out = support.read_cells_support(np.zeros((10, 10, 3), np.uint8), [6, 1], "auto")      # Alignment, Alignment
    assert [(d["cell"], d["pip"]) for d in out] == [(6, 6), (1, 7)]


def test_read_cells_support_rejects_cells_outside_1_15(fakes):
    fakes.setattr(support, "star_prob", lambda hr: None)
    frame = np.zeros((10, 10, 3), np.uint8)
    for bad in ([0], [-1], [16], [9, 0, 2]):
        with pytest.raises(ValueError):
            support.read_cells_support(frame, bad, "auto")
    assert [d["cell"] for d in support.read_cells_support(frame, [9, 2, 15], "auto")] == [9, 2, 15]


def test_read_conf_min_value():
    assert support.READ_CONF_MIN == 0.90


# ---- report ----

def arrays(conf, ok):
    yt = ["A"] * len(conf)
    yp = ["A" if o else "B" for o in ok]
    return yt, yp, conf


def test_report_lines_and_threshold_edges():
    conf = [0.50] * 2 + [0.95] * 18                    # 20 crops
    ok = [False] + [True] * 19
    lines, t = cr.report(*arrays(conf, ok))
    assert len(lines) == 7
    assert lines[0] == "conf >= 0.50: kept 20/20 (100.0%), accuracy of kept 0.950, wrong kept 1, wrong dropped 0"
    assert lines[1] == "conf >= 0.60: kept 18/20 (90.0%), accuracy of kept 1.000, wrong kept 0, wrong dropped 1"
    assert lines[5].startswith("conf >= 0.95: kept 18/20")             # conf == T is kept
    assert lines[6] == "chosen READ_CONF_MIN = 0.50 (largest with kept >= 95%)"
    assert t == 0.50


def test_report_chosen_is_largest_keeping_95_percent():
    conf = [0.55] * 1 + [0.85] * 99                   # 1% below 0.60.. -> kept 99% up to 0.80
    lines, t = cr.report(*arrays(conf, [True] * 100))
    assert t == 0.80 and lines[-1] == "chosen READ_CONF_MIN = 0.80 (largest with kept >= 95%)"


def test_report_exactly_95_percent_counts():
    conf = [0.70] * 1 + [0.99] * 19
    assert cr.report(*arrays(conf, [True] * 20))[1] == 0.95


def test_report_none_keeps_95_percent_gives_050_and_empty_kept_accuracy():
    conf = [0.10] * 20
    lines, t = cr.report(*arrays(conf, [True] * 20))
    assert t == 0.50
    assert lines[0] == "conf >= 0.50: kept 0/20 (0.0%), accuracy of kept 0.000, wrong kept 0, wrong dropped 0"
    assert lines[-1] == "chosen READ_CONF_MIN = 0.50 (largest with kept >= 95%)"


# ---- main ----

def make_data(tmp_path, games, manifest=None, chk=True):
    d = tmp_path / "data"
    s = d / "crops_support"
    s.mkdir(parents=True)
    n = len(games)
    np.savez(s / "feats_sup1.npz", names=np.array([f"n{i}" for i in range(n)]))
    np.save(s / "y_sup1.npy", np.array(["Bubble"] * n, dtype=object))
    np.save(s / "pip_sup1.npy", np.ones(n, int))
    np.save(s / "grp_sup1.npy", np.array(games))
    np.save(s / "eff_sup1.npy", np.zeros(n, bool))
    np.save(s / "chk_sup1.npy", np.full(n, chk))
    if manifest is not None:
        (d / C.MANIFEST).write_text(json.dumps(manifest))
    return d


def test_main_refuses_holdout_game_used_in_training(tmp_path, capsys):
    d = make_data(tmp_path, ["gH"], {"support_type_cnn.pt": ["gH"]})
    assert cr.main(["--holdout", "gH", "--tags", "sup1", "--data-dir", str(d)]) == 1
    assert capsys.readouterr().out.strip() == "FAIL: holdout game gH was used in training"


def test_main_no_checked_crops(tmp_path, capsys):
    d = make_data(tmp_path, ["gH"], chk=False)
    assert cr.main(["--holdout", "gH", "--tags", "sup1", "--data-dir", str(d)]) == 1
    assert capsys.readouterr().out.strip() == "FAIL: no checked crops in the holdout games"
    d2 = make_data(tmp_path / "b", ["gOther"])
    assert cr.main(["--holdout", "gH", "--tags", "sup1", "--data-dir", str(d2)]) == 1
    assert capsys.readouterr().out.strip() == "FAIL: no checked crops in the holdout games"
