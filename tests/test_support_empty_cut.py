"""EMPTY_CONF_MIN (rdf03-t7): the --empty report, its choice rule and the stricter cut in _unreadable."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from rdom.perception import support
from rdom.perception import support_memory as sm
from rdom.perception.support_memory import CellMemory, burst_result, merge_verdict

import support_conf_report as cr
import support_players as sp
import support_train_common as C

CM = 0.9


def rd(cell, typ="Resonance", pip=3, conf=0.99):
    return {"cell": cell, "type": typ, "variant": typ, "pip": pip, "conf": conf}


# ---- report_empty ----

def empty_arrays(true_conf, other_conf):
    """true_conf: reviewed empty read empty; other_conf: reviewed junk read empty. Plus one non-empty read (ignored)."""
    yt = ["empty"] * len(true_conf) + ["junk"] * len(other_conf) + ["Bubble"]
    yp = ["empty"] * (len(true_conf) + len(other_conf)) + ["Bubble"]
    return yt, yp, list(true_conf) + list(other_conf) + [0.99]


def test_report_empty_separable():
    lines, t = cr.report_empty(*empty_arrays([0.99] * 50, [0.93]))
    assert len(lines) == 11
    assert lines[0] == "empty conf >= 0.90: kept 50/50 true empty, rejected 0/1 other read as empty"
    assert lines[3] == "empty conf >= 0.93: kept 50/50 true empty, rejected 0/1 other read as empty"   # conf == T is kept
    assert lines[4] == "empty conf >= 0.94: kept 50/50 true empty, rejected 1/1 other read as empty"
    assert lines[9] == "empty conf >= 0.99: kept 50/50 true empty, rejected 1/1 other read as empty"
    assert lines[10] == "chosen EMPTY_CONF_MIN = 0.94" and t == 0.94


def test_report_empty_not_separable_when_true_empties_fall_below():
    # the other read sits at 0.95, but half the true empties are below it
    lines, t = cr.report_empty(*empty_arrays([0.92] * 25 + [0.99] * 25, [0.95]))
    assert lines[5] == "empty conf >= 0.95: kept 25/50 true empty, rejected 0/1 other read as empty"
    assert lines[6] == "empty conf >= 0.96: kept 25/50 true empty, rejected 1/1 other read as empty"
    assert lines[-1] == "no EMPTY_CONF_MIN separates them -- unchanged" and t is None


def test_report_empty_needs_98_percent_of_true_empties():
    assert cr.report_empty(*empty_arrays([0.905] + [0.99] * 49, [0.905]))[1] == 0.91      # 49/50 = 0.98
    assert cr.report_empty(*empty_arrays([0.905] * 2 + [0.99] * 48, [0.905]))[1] is None  # 48/50


def test_report_empty_ignores_other_reads_below_read_conf_min():
    lines, t = cr.report_empty(*empty_arrays([0.99] * 10, [0.85]))
    assert lines[0] == "empty conf >= 0.90: kept 10/10 true empty, rejected 0/0 other read as empty"
    assert t == 0.90


def make_data(tmp_path, games, manifest=None):
    d = tmp_path / "data"
    s = d / "crops_support"
    s.mkdir(parents=True)
    n = len(games)
    np.savez(s / "feats_sup1.npz", names=np.array([f"n{i}" for i in range(n)]))
    np.save(s / "y_sup1.npy", np.array(["empty", "junk"][:n], dtype=object))
    np.save(s / "pip_sup1.npy", np.ones(n, int))
    np.save(s / "grp_sup1.npy", np.array(games))
    np.save(s / "eff_sup1.npy", np.zeros(n, bool))
    np.save(s / "chk_sup1.npy", np.full(n, True))
    if manifest is not None:
        (d / C.MANIFEST).write_text(json.dumps(manifest))
    return d


def test_main_empty_flag_prints_empty_lines_and_default_output_unchanged(tmp_path, capsys, monkeypatch):
    d = make_data(tmp_path, ["gH", "gH"])
    monkeypatch.setattr(cr.C, "read_rgb", lambda p: np.zeros((8, 8, 3), np.uint8))
    monkeypatch.setattr(cr.support, "predict_types_support", lambda crops: (["empty", "empty"], [0.99, 0.92]))
    args = ["--holdout", "gH", "--tags", "sup1", "--data-dir", str(d)]
    assert cr.main(args + ["--empty"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "empty conf >= 0.90: kept 1/1 true empty, rejected 0/1 other read as empty"
    assert out[-1] == "chosen EMPTY_CONF_MIN = 0.93"
    assert cr.main(args) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("conf >= 0.50: kept 2/2")


def test_main_empty_flag_same_refusals(tmp_path, capsys):
    d = make_data(tmp_path, ["gH"], {"support_type_cnn.pt": ["gH"]})
    assert cr.main(["--holdout", "gH", "--tags", "sup1", "--data-dir", str(d), "--empty"]) == 1
    assert capsys.readouterr().out.strip() == "FAIL: holdout game gH was used in training"
    d2 = make_data(tmp_path / "b", ["gH"])
    assert cr.main(["--holdout", "gH", "--tags", "nope", "--data-dir", str(d2), "--empty"]) == 1
    assert capsys.readouterr().out.startswith("FAIL: no feats file for tag nope")


# ---- _unreadable ----

def test_unreadable_empty_below_and_at_the_empty_cut():
    cut = 0.93
    assert sm._unreadable(rd(1, "empty", 0, 0.929), CM, cut)
    assert not sm._unreadable(rd(1, "empty", 0, 0.93), CM, cut)
    assert sm._unreadable(rd(1, "empty", 0, 0.5), CM, cut)


def test_unreadable_non_empty_types_ignore_the_empty_cut():
    for typ in ("Resonance", "Bubble", "Bomb"):
        assert not sm._unreadable(rd(1, typ, 3, 0.91), CM, 0.99)
        assert sm._unreadable(rd(1, typ, 3, 0.89), CM, 0.5)
    assert sm._unreadable(rd(1, "junk", 0, 1.0), CM, 0.5)
    assert sm._unreadable(rd(1, "empty", 0, float("nan")), CM, 0.5)


def test_empty_cut_equal_to_conf_min_behaves_as_before():
    for typ in ("empty", "Resonance", "junk"):
        for conf in (0.5, 0.899, 0.9, 0.95, float("nan")):
            d = rd(1, typ, 0, conf)
            assert sm._unreadable(d, CM, CM) == sm._unreadable(d, CM)


def test_empty_conf_min_is_read_conf_min_when_nothing_separates():
    assert support.EMPTY_CONF_MIN == support.READ_CONF_MIN


def test_memory_burst_verdict_and_burster_follow_the_empty_cut():
    flash = rd(1, "empty", 0, 0.909)
    board = [rd(c, "empty", 0, 0.99) for c in range(1, 16)]
    board[0] = flash
    eff, _ = CellMemory(CM, empty_conf_min=0.91).update(board)
    assert eff[0]["type"] == "junk" and eff[0]["src"] == "unknown"
    assert CellMemory(CM).update(board)[0][0]["type"] == "empty"
    assert burst_result([flash, flash], CM) == ("empty", 0)
    assert burst_result([flash, flash], CM, empty_conf_min=0.91) is None
    other = rd(2, "empty", 0, 0.99)
    assert merge_verdict(flash, other, ("Resonance", 3), ("empty", 0), CM) == "effect"
    assert merge_verdict(flash, other, ("Resonance", 3), ("empty", 0), CM, 0.91) == "undecided"

    class P:
        pass
    b = sp.Burster(P())
    b.done(0.0, [1], {1: None}, {1: [flash]}, CM)
    assert b.fails[1] == 0                      # confident empty
    b.done(1.0, [1], {1: None}, {1: [flash]}, CM, 0.91)
    assert b.fails[1] == 1                      # the flash no longer counts as a confident read
