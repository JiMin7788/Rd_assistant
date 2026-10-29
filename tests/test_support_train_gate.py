import json
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from rdom.perception import gear, support

import support_gate as sg
import support_train_common as C
import train_support_pip as tsp
import train_support_star as tss
import train_support_type_cnn as tst


def write_png(path, value=None, size=72, seed=0):
    img = (np.random.RandomState(seed).randint(0, 256, (size, size, 3)).astype(np.uint8)
           if value is None else np.full((size, size, 3), value, np.uint8))
    cv2.imwrite(str(path), img)      # BGR order is irrelevant for noise / constant images


def make_tree(root):
    """data/ with a tiny gear tag s2 (+ stray y_init / pip_bomb files without twins) and support tag sup1."""
    g, s = root / "crops_gear", root / "crops_support"
    for d in (g / "_raw", s / "_raw", s / "_hires"):
        d.mkdir(parents=True)
    gy = ["Bubble", "Adjust", "GearRed", "junk"] * 6
    names = [f"g{i}" for i in range(24)]
    for i, n in enumerate(names):
        write_png(g / "_raw" / f"{n}.png", seed=i)
    np.savez(g / "feats_s2.npz", names=np.array(names))
    np.save(g / "y_s2.npy", np.array(gy, dtype=object))
    np.save(g / "pip_s2.npy", np.array([(i % 7) + 1 for i in range(24)]))
    np.save(g / "y_init.npy", np.array(["Bubble"], dtype=object))      # real data: label files without a feats_ twin
    np.save(g / "pip_bomb.npy", np.array([1]))                          # ... and a pip_ file without grp_
    types = ["Resonance", "Alignment", "Bubble", "empty"] * 12
    sn = [f"c{i}" for i in range(48)]
    for i, n in enumerate(sn):
        write_png(s / "_raw" / f"{n}.png", seed=100 + i)
        write_png(s / "_hires" / f"{n}.png", size=128, seed=200 + i)
    np.savez(s / "feats_sup1.npz", names=np.array(sn))
    np.save(s / "y_sup1.npy", np.array(types, dtype=object))
    np.save(s / "pip_sup1.npy", np.array([0 if t == "empty" else (i % 7) + 1 for i, t in enumerate(types)]))
    np.save(s / "grp_sup1.npy", np.array([("gA", "gB", "gC")[i % 3] for i in range(48)]))
    np.save(s / "eff_sup1.npy", np.zeros(48, bool))
    np.save(s / "chk_sup1.npy", np.ones(48, bool))
    return root


@pytest.fixture
def tree(tmp_path):
    return make_tree(tmp_path / "data")


def load_state(path, n_out):
    import torch
    net = gear._pipnet_cls()(n_out=n_out)
    net.load_state_dict(torch.load(path))
    return net


# ---- trainers ----

def test_type_trainer_maps_labels_excludes_games_and_saves_atomically(tree):
    X, Y = tst.gear_data(str(tree / "crops_gear"))
    assert len(Y) == 18                                   # GearRed dropped; stray y_init.npy ignored
    assert {support.SUPPORT_CLASSES[y] for y in Y} == {"Bubble", "Adjust", "junk"}
    tst.main(["--data-dir", str(tree), "--epochs", "1", "--exclude-games", "gB"])
    out = tree / support.TYPE_FILE
    assert out.exists() and not (tree / (support.TYPE_FILE + ".tmp")).exists()
    load_state(out, len(support.SUPPORT_CLASSES))
    assert json.loads((tree / C.MANIFEST).read_text())[support.TYPE_FILE] == ["gA", "gC"]


def test_star_trainer_n_out_1_and_manifest_merge(tree):
    (tree / C.MANIFEST).write_text(json.dumps({"other.pt": ["gZ"]}))
    out = tree / "star_x.pt"
    tss.main(["--data-dir", str(tree), "--epochs", "1", "--seed", "3", "--out", str(out)])
    load_state(out, 1)
    m = json.loads((tree / C.MANIFEST).read_text())
    assert m["other.pt"] == ["gZ"] and m["star_x.pt"] == ["gA", "gB", "gC"]      # merged, not overwritten


def test_pip_trainer_pattern_head_without_pip7(tree, monkeypatch):
    seen = {}
    real = tsp.tp.train

    def spy(X, T, P, epochs, seed=0, log=None):
        seen.update(P=P, T=T, pattern=tsp.tp.PATTERN)
        return real(X, T, P, epochs, seed=seed, log=log)
    monkeypatch.setattr(tsp.tp, "train", spy)
    monkeypatch.setattr(tsp.tp, "PATTERN", False)
    tsp.main(["--data-dir", str(tree), "--epochs", "1", "--seed", "2"])    # pip_bomb.npy has no grp_ twin: skipped
    assert seen["pattern"] and seen["P"].max() <= 5 and seen["P"].min() >= 0     # pip 7 (index 6) excluded
    assert not seen["T"].any()
    load_state(tree / "support_pip_pat_e2.pt", 7)
    assert json.loads((tree / C.MANIFEST).read_text())["support_pip_pat_e2.pt"] == ["gA", "gB", "gC"]


# ---- metrics / verdict ----

def crops(spec):
    """spec: list of (human type, pred type, human pip, pred pip, eff, count) -> metric inputs."""
    cols = ([], [], [], [], [])           # in the argument order of sg.metrics
    for yt, yp, pt, pp, eff, n in spec:
        for col, v in zip(cols, (yt, yp, eff, pt, pp)):
            col.extend([v] * n)
    return cols


def test_type_recall_not_precision_and_pass():
    spec = [("Resonance", "Resonance", 1, 1, True, 60), ("Alignment", "Alignment", 1, 1, True, 95),
            ("Alignment", "junk", 1, 1, True, 5), ("Bubble", "Bubble", 1, 1, True, 200),
            ("Joker", "Alignment", 1, 1, True, 30)]                  # Alignment precision 95/125 is low
    m = sg.metrics(*crops(spec))
    assert m["type"]["Alignment"] == pytest.approx(0.95) and m["type"]["Resonance"] == 1.0
    ok, _, lines = sg.verdict(m)
    assert ok and lines[0].startswith("type gate: PASS (") and "too few" not in lines[0]


def test_type_too_few_alignment_and_threshold():
    spec = [("Resonance", "Resonance", 1, 1, True, 60), ("Alignment", "Alignment", 1, 1, True, 49),
            ("Bubble", "Bubble", 1, 1, True, 200)]
    ok, _, lines = sg.verdict(sg.metrics(*crops(spec)))
    assert not ok and lines[0].startswith("type gate: FAIL (") and lines[0].endswith(" too few samples")
    spec = [("Resonance", "Resonance", 1, 1, True, 50), ("Alignment", "Alignment", 1, 1, True, 50),
            ("Alignment", "junk", 1, 1, True, 6), ("Bubble", "Bubble", 1, 1, True, 400)]   # Alignment 50/56 < 0.9
    ok, _, _ = sg.verdict(sg.metrics(*crops(spec)))
    assert not ok
    spec = [("Resonance", "Resonance", 1, 1, True, 50), ("Alignment", "Alignment", 1, 1, True, 50),
            ("Bubble", "junk", 1, 1, True, 20), ("Bubble", "Bubble", 1, 1, False, 400)]    # effect 100/120 < 0.9
    m = sg.metrics(*crops(spec))
    assert m["type"]["effect"] < 0.9 and m["type"]["overall"] >= 0.9 and not sg.verdict(m)[0]


def pip_spec(stars):
    return [("Resonance", "Resonance", 7, 7, True, stars), ("Resonance", "Resonance", 7, 6, True, 2),
            ("Resonance", "Resonance", 3, 3, False, 40), ("Alignment", "Alignment", 2, 2, True, 40)]


def test_star_recall_precision_and_pip_pass():
    m = sg.metrics(*crops(pip_spec(28) + [("Bubble", "Bubble", 1, 7, True, 0)]))
    p = m["pip"]
    assert p["stars"] == 30 and p["star_recall"] == pytest.approx(28 / 30) and p["star_precision"] == 1.0
    assert p["res_align"] == pytest.approx(108 / 110) and p["n"] == 110
    _, ok, lines = sg.verdict(m)
    assert ok and lines[1].startswith("pip gate: PASS (")
    # a Bubble predicted 7 lowers precision (human 7 among predicted 7), not recall
    m = sg.metrics(*crops(pip_spec(28) + [("Bubble", "Bubble", 1, 7, True, 10)]))
    assert m["pip"]["star_precision"] == pytest.approx(28 / 38) and m["pip"]["star_recall"] == pytest.approx(28 / 30)
    assert not sg.verdict(m)[1]


def test_pip_too_few_stars():
    m = sg.metrics(*crops(pip_spec(27)))                             # 27 + 2 = 29 pip-7 crops
    assert m["pip"]["stars"] == 29
    ok, lines = sg.verdict(m)[1], sg.verdict(m)[2]
    assert not ok and lines[1].endswith(" too few samples")


def test_printed_line_formats():
    t = {"n": 812, "overall": 0.9534, "effect": 0.9211, "Resonance": 0.9701, "Alignment": 0.9444,
         "n_Resonance": 100, "n_Alignment": 100}
    p = {"n": 640, "res_align": 0.8711, "effect": 0.8401, "star_recall": 0.7, "star_precision": 0.95, "stars": 20}
    lines = sg.verdict({"type": t, "pip": p})[2]
    assert lines[0] == "type gate: PASS (overall 0.953, effect 0.921, Resonance 0.970, Alignment 0.944, n=812)"
    # stars=20 < 30: the AC6 suffix follows the AC7 format
    assert lines[1] == ("pip gate: FAIL (Res/Align 0.871, effect 0.840, star recall 0.700, star precision 0.950, "
                        "n=640, stars=20) too few samples")
    p["stars"] = 30
    assert sg.verdict({"type": t, "pip": p})[2][1].endswith("n=640, stars=30)")


# ---- gate tool ----

@pytest.fixture
def gate_env(tmp_path, monkeypatch):
    """Holdout games gH1/gH2 (checked + unticked crops), train game gT, fake models keyed by the idx in the pixels."""
    d = tmp_path / "data"
    s = d / "crops_support"
    for sub in ("_raw", "_hires"):
        (s / sub).mkdir(parents=True)
    rows = []        # (type, pip, game, eff, chk)
    rows += [("Resonance", 7, "gH1", i % 2 == 0, True) for i in range(30)]
    rows += [("Resonance", 3, "gH2", i % 2 == 0, True) for i in range(30)]
    rows += [("Alignment", 2, "gH1" if i % 2 else "gH2", i % 3 == 0, True) for i in range(60)]
    rows += [("Bubble", 1, "gH1", False, True) for _ in range(20)]
    rows += [("Alignment", 2, "gH1", True, False) for _ in range(20)]       # unticked pre-labels: never evaluated
    rows += [("Resonance", 3, "gT", False, True) for _ in range(20)]         # not a holdout game
    names = [f"n{i}" for i in range(len(rows))]
    for i, n in enumerate(names):
        write_png(s / "_raw" / f"{n}.png", value=i)
        write_png(s / "_hires" / f"{n}.png", value=i, size=128)
    np.savez(s / "feats_sup1.npz", names=np.array(names))
    np.save(s / "y_sup1.npy", np.array([r[0] for r in rows], dtype=object))
    np.save(s / "pip_sup1.npy", np.array([r[1] for r in rows]))
    np.save(s / "grp_sup1.npy", np.array([r[2] for r in rows]))
    np.save(s / "eff_sup1.npy", np.array([r[3] for r in rows]))
    np.save(s / "chk_sup1.npy", np.array([r[4] for r in rows]))
    for f in [support.TYPE_FILE] + list(support.PIP_FILES) + list(support.STAR_FILES):
        (d / f).write_bytes(f.encode())
    monkeypatch.setattr(support, "_DATA", str(d))
    monkeypatch.setattr(support, "_models", {})
    idx = lambda crops: [int(c[0, 0, 0]) for c in crops]
    # perfect on checked crops, wrong (junk / pip 1) on unticked ones
    monkeypatch.setattr(support, "predict_types_support",
                        lambda cr: ([rows[i][0] if rows[i][4] else "junk" for i in idx(cr)], [1.0] * len(cr)))
    monkeypatch.setattr(support, "predict_pips_support",
                        lambda cr, src="auto": [rows[i][1] if rows[i][4] else 1 for i in idx(cr)])
    monkeypatch.setattr(support, "star_prob", lambda hr: np.array([1.0 if rows[i][1] == 7 else 0.0 for i in idx(hr)]))
    return d, rows


def test_gate_main_writes_json_and_round_trips(gate_env, capsys):
    d, rows = gate_env
    assert sg.main(["--holdout", "gH1,gH2", "--data-dir", str(d)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("type gate: PASS (") and out[0].endswith("n=140)")      # only the checked holdout crops
    assert out[1].startswith("pip gate: PASS (") and "n=120, stars=30)" in out[1]
    assert out[2] == f"written {d / support.GATE_FILE}"      # the real path, not a fixed data/ one
    g = json.loads((d / support.GATE_FILE).read_text())
    assert g["holdout"] == ["gH1", "gH2"] and g["created"]
    assert g["type"]["pass"] is True and g["pip"]["pass"] is True
    assert g["type"]["effect"] == 1.0 and g["type"]["n"] == 140
    assert sorted(g["models"]) == sorted(support.model_files())
    assert g["models"][support.TYPE_FILE] == support._sha256(str(d / support.TYPE_FILE))
    assert support.gate_state() == {"type": True, "pip": True}
    (d / support.TYPE_FILE).write_bytes(b"retrained")                                  # sha256 no longer matches
    assert support.gate_state() == {"type": False, "pip": False}


def test_gate_effect_flag_and_failure_flags(gate_env, monkeypatch, capsys):
    d, rows = gate_env
    monkeypatch.setattr(support, "predict_types_support",       # every effect Alignment crop misread
                        lambda cr: ([("junk" if rows[int(c[0, 0, 0])][3] and rows[int(c[0, 0, 0])][0] == "Alignment"
                                      else rows[int(c[0, 0, 0])][0]) for c in cr], [1.0] * len(cr)))
    assert sg.main(["--holdout", "gH1,gH2", "--data-dir", str(d)]) == 0
    assert capsys.readouterr().out.startswith("type gate: FAIL (")
    g = json.loads((d / support.GATE_FILE).read_text())
    assert g["type"]["pass"] is False and g["pip"]["pass"] is True
    assert support.gate_state() == {"type": False, "pip": True}


def test_gate_refuses_holdout_used_in_training(gate_env, capsys):
    d, _ = gate_env
    (d / C.MANIFEST).write_text(json.dumps({"support_type_cnn.pt": ["gT"], "support_star_e1.pt": ["gH2"]}))
    assert sg.main(["--holdout", "gH1,gH2", "--data-dir", str(d)]) == 1
    assert capsys.readouterr().out.strip() == "FAIL: holdout game gH2 was used in training"
    assert not (d / support.GATE_FILE).exists()


def test_gate_only_checked_crops_of_holdout_games(gate_env):
    d, rows = gate_env
    got = sg._holdout_rows(str(d / "crops_support"), [], ["gH1"])
    assert len(got) == sum(1 for r in rows if r[2] == "gH1" and r[4])
    assert all(r[0] != "n999" for r in got)
