"""Input hardening found by QA round 3 (rdf02-m1): non-finite conf, bool cells, --help, missing tag."""
import os
import subprocess
import sys

import numpy as np
import pytest

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, TOOLS)
from rdom.perception import gear, support
from rdom.perception.support_memory import CellMemory, burst_result, merge_verdict

import support_conf_report as cr

CM = 0.9
NAN = float("nan")


def rd(cell, typ="Resonance", pip=3, conf=0.99):
    return {"cell": cell, "type": typ, "variant": typ, "pip": pip, "conf": conf}


def board(**over):
    b = [rd(c, "empty", 0, 0.99) for c in range(1, 16)]
    for c, d in over.items():
        b[int(c[1:]) - 1] = d
    return b


# ---- AC4 ----

def test_nan_conf_is_unreadable_in_update():
    m = CellMemory(CM)
    for _ in range(2):
        m.update(board(c1=rd(1)))
    assert m.memory(1) == ("Resonance", 3)
    for bad in (NAN, float("inf"), None):
        read = rd(1, "Alignment", 5, bad)
        eff, _ = m.update(board(c1=read))
        assert m.unreadable(read)
        assert eff[0]["src"] == "memory" and eff[0]["type"] == "Resonance"
    assert m.memory(1) == ("Resonance", 3) and 1 not in m._pend      # a NaN read starts no confirmation
    eff, _ = CellMemory(CM).update(board(c2=rd(2, conf=NAN)))
    assert eff[1]["src"] == "unknown"


def test_burst_result_never_accepts_non_finite_conf():
    assert burst_result([rd(1, conf=NAN)] * 6, CM) is None
    assert burst_result([rd(1, conf=float("inf"))] * 6, CM) is None
    mixed = [rd(1, "Alignment", 2, NAN)] * 4 + [rd(1)] * 2
    assert burst_result(mixed, CM) == ("Resonance", 3)
    v = merge_verdict(rd(1, "empty", 0, NAN), rd(2, conf=NAN), ("Resonance", 3), ("Resonance", 3), CM)
    assert v == "undecided"


def test_burster_done_non_finite_conf_does_not_reset_fail_counter():
    import support_players as sp
    b = sp.Burster(None)
    nan_reads = {3: [rd(3, conf=NAN), rd(3, conf=float("inf"))]}
    for i in range(1, 4):
        b.done(10.0 * i, [3], {3: None}, nan_reads, CM)
    assert b.fails[3] == 3
    b.done(50.0, [3], {3: None}, {3: [rd(3)]}, CM)         # a finite confident read still resets
    assert b.fails[3] == 0


# ---- AC6 ----

@pytest.mark.parametrize("bad", [[True], [2.5], [3, False], ["4"], [None], [1.0]])
def test_read_cells_support_rejects_bool_and_non_int_cells(monkeypatch, bad):
    def boom(f):
        raise AssertionError("nothing may be read")
    monkeypatch.setattr(gear, "cell_crops", boom)
    with pytest.raises(ValueError, match="cells must be in 1..15"):
        support.read_cells_support(np.zeros((10, 10, 3), np.uint8), bad, "auto")


# ---- AC5 ----

def test_dryrun_help_prints_usage(capsys):
    import support_dryrun
    for flag in ("--help", "-h"):
        assert support_dryrun.main([flag]) == 0
    assert capsys.readouterr().out.count("usage: python tools/support_dryrun.py") == 2


def test_dryrun_help_subprocess_exit_0(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "support_dryrun.py"), "--help"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "usage:" in r.stdout and "Traceback" not in r.stderr
    assert not os.listdir(tmp_path)


def test_build_digit_templates_help_writes_nothing(tmp_path):
    out_dir = os.path.join(TOOLS, "..", "assets", "templates")
    before = sorted(os.listdir(out_dir))
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "build_digit_templates.py"), "--help"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "usage:" in r.stdout and "Traceback" not in r.stderr
    assert sorted(os.listdir(out_dir)) == before and not os.listdir(tmp_path)


# ---- AC7 ----

def test_conf_report_missing_feats_tag_is_one_fail_line(tmp_path, capsys):
    s = tmp_path / "data" / "crops_support"
    s.mkdir(parents=True)
    np.savez(s / "feats_sup1.npz", names=np.array(["n0"]))
    rc = cr.main(["--holdout", "gH", "--tags", "sup1,nope", "--data-dir", str(tmp_path / "data")])
    lines = capsys.readouterr().out.strip().splitlines()
    assert rc == 1 and len(lines) == 1
    assert lines[0].startswith("FAIL:") and "nope" in lines[0] and "sup1" not in lines[0].split(" in ")[0]
