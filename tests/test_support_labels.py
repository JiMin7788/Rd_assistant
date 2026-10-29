import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import gear, support

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pl = _load("support_prelabel")
rv = _load("support_review")
bt = _load("build_support_tag")


def _write_crops(d, specs):
    """specs: [(game, t, cell, rgb_colour, extra_meta)] -> crops.jsonl + _raw/_hires PNGs."""
    (d / "_raw").mkdir(parents=True, exist_ok=True)
    (d / "_hires").mkdir(exist_ok=True)
    lines = []
    for game, t, cell, rgb, extra in specs:
        name = f"{game}_{t:.1f}_{cell:02d}"
        for sub, size in (("_raw", 72), ("_hires", 128)):
            im = np.zeros((size, size, 3), np.uint8); im[:] = rgb
            cv2.imwrite(str(d / sub / (name + ".png")), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
        lines.append({"name": name, "game": game, "t": t, "cell": cell,
                      "buffed": False, "glare": False, **extra})
    (d / "crops.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    return [r["name"] for r in lines]


def _patch_gear(monkeypatch, types, pip_of):
    monkeypatch.setattr(gear, "set_deck", lambda n: None)
    monkeypatch.setattr(gear, "predict_types", types)
    monkeypatch.setattr(gear, "predict_pips", lambda crops, ts: [pip_of(c) for c in crops])
    monkeypatch.setattr(support, "star_prob", lambda crops: None)


def _read(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]


def test_prelabel_types_pips_keys(tmp_path, monkeypatch):
    green, black, yellow, grey, blue = (0, 200, 0), (10, 10, 10), (230, 210, 20), (128, 128, 128), (0, 0, 255)
    names = _write_crops(tmp_path, [("g", 1.0, i + 1, c, {}) for i, c in enumerate((green, black, yellow, grey, blue))])

    def types(crops):                  # confident Bubble only for the blue crop, weak gear read otherwise
        return (["Bubble" if c[0, 0, 2] == 255 else "GearTeal" for c in crops],
                [0.95 if c[0, 0, 2] == 255 else 0.5 for c in crops])

    _patch_gear(monkeypatch, types, lambda c: 2)
    pl.main(["--dir", str(tmp_path)])
    rows = _read(tmp_path / "prelabels.jsonl")
    assert [r["name"] for r in rows] == names
    assert [r["type"] for r in rows] == ["Resonance", "Alignment", "Alignment", "?", "Bubble"]
    assert [r["src"] for r in rows][:3] == ["colour"] * 3 and rows[4]["src"] == "gear-model"
    assert [r["ambiguous"] for r in rows] == [True, True, True, True, False]
    assert all(set(r) == {"name", "type", "pip", "src", "ambiguous", "star_cand"} for r in rows)
    assert rows[0]["pip"] == 2 and rows[4]["pip"] == 2


def test_prelabel_low_confidence_gear_label_goes_to_colour(tmp_path, monkeypatch):
    _write_crops(tmp_path, [("g", 1.0, 1, (0, 200, 0), {})])
    _patch_gear(monkeypatch, lambda crops: (["Bubble"] * len(crops), [0.89] * len(crops)), lambda c: 1)
    assert pl.prelabel(str(tmp_path))[0]["type"] == "Resonance"


def test_prelabel_star_candidate_after_pip6(tmp_path, monkeypatch):
    # red channel encodes the pip (x10); green face keeps the colour rule on Resonance
    names = _write_crops(tmp_path, [("g", 1.0, 3, (60, 200, 0), {}), ("g", 2.0, 3, (10, 200, 0), {}),
                                    ("g", 3.0, 3, (10, 200, 0), {})])
    _patch_gear(monkeypatch, lambda crops: (["GearTeal"] * len(crops), [0.1] * len(crops)),
                lambda c: int(c[0, 0, 0]) // 10)
    rows = pl.prelabel(str(tmp_path))
    assert [r["pip"] for r in rows] == [6, 1, 1]
    assert [r["star_cand"] for r in rows] == [False, True, False]


def test_prelabel_star_probability(tmp_path, monkeypatch):
    _write_crops(tmp_path, [("g", 1.0, 1, (10, 200, 0), {}), ("g", 2.0, 2, (10, 200, 0), {})])
    _patch_gear(monkeypatch, lambda crops: (["GearTeal"] * len(crops), [0.1] * len(crops)), lambda c: 1)
    monkeypatch.setattr(support, "star_prob", lambda crops: np.array([0.31, 0.3]))
    assert [r["star_cand"] for r in pl.prelabel(str(tmp_path))] == [True, False]


def test_colour_rule_only_in_tools():
    for p in (ROOT / "src" / "rdom").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "support_prelabel" not in src, p
        assert "_colour_label" not in src, p


# ---- review sheets ----

def _pre(name, typ="Resonance", pip=1, amb=True, star=False):
    return {"name": name, "type": typ, "pip": pip, "src": "colour", "ambiguous": amb, "star_cand": star}


def _write_pre(d, rows):
    d.mkdir(parents=True, exist_ok=True)
    (d / "prelabels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _index(path):
    return [l.split("\t") for l in Path(path).read_text(encoding="utf-8").splitlines()]


def test_caption_fits_tile():
    for typ in list(support.SUPPORT_CLASSES) + ["?"]:
        for idx, pip in ((49, 7), (0, 0), (49, 6)):
            text = rv.caption_text(idx, typ, pip)
            w = cv2.getTextSize(text, rv.FONT, rv.caption_scale(text), 1)[0][0]
            assert w + 4 <= rv.TILE - 2, text            # text + black box padding


def test_ambiguous_sheets_single_type(tmp_path):
    _write_pre(tmp_path, [_pre(f"g_{i:04d}") for i in range(120)])
    rv.main(["--ambiguous", "--dir", str(tmp_path)])
    out = tmp_path / "review" / "amb"
    assert sorted(p.name for p in out.glob("sheet_*.png")) == ["sheet_00.png", "sheet_01.png", "sheet_02.png"]
    assert len(_index(out / "index.tsv")) == 120
    img = cv2.imread(str(out / "sheet_00.png"))
    assert img.shape == (5 * 128, 10 * 128, 3)
    first = _index(out / "index.tsv")[0]
    assert len(first) == 5 and first[0] == "sheet_00" and first[1] == "0"


def test_ambiguous_prints_sheet_paths(tmp_path, capsys):
    _write_pre(tmp_path, [_pre(f"g_{i:04d}") for i in range(120)])
    rv.main(["--ambiguous", "--dir", str(tmp_path)])
    lines = capsys.readouterr().out.splitlines()
    out = tmp_path / "review" / "amb"
    for name in ("sheet_00.png", "sheet_01.png", "sheet_02.png", "index.tsv"):
        assert str(out / name) in lines
        assert (out / name).exists()


def test_ambiguous_mixed_types_and_star_separate(tmp_path):
    rows = ([_pre(f"a_{i:03d}", "Resonance") for i in range(60)] + [_pre(f"b_{i:03d}", "Alignment") for i in range(30)]
            + [_pre(f"c_{i:03d}", "Resonance", star=True) for i in range(10)]
            + [_pre(f"d_{i:03d}", "Bubble", amb=False) for i in range(10)])    # not ambiguous: not cut
    _write_pre(tmp_path, rows)
    rv.ambiguous(str(tmp_path))
    idx = _index(tmp_path / "review" / "amb" / "index.tsv")
    assert len(idx) == 100
    by_sheet = {}
    for sheet, _, name, typ, _ in idx:
        by_sheet.setdefault(sheet, set()).add((typ, name[0] == "c"))
    assert all(len(v) == 1 for v in by_sheet.values())
    assert len(by_sheet) == 4


def test_ambiguous_skips_ticked_and_never_reuses_numbers(tmp_path):
    _write_pre(tmp_path, [_pre(f"g_{i:03d}") for i in range(70)])
    rv.ambiguous(str(tmp_path))
    out = tmp_path / "review" / "amb"
    (out / "fixes.tsv").write_text("sheet_00\tok\nsheet_01:3\tdrop\n", encoding="utf-8")
    before = [r for r in _index(out / "index.tsv") if r[0] == "sheet_00"]
    rv.ambiguous(str(tmp_path))
    idx = _index(out / "index.tsv")
    assert [r for r in idx if r[0] == "sheet_00"] == before                   # ticked sheet untouched
    assert len({r[2] for r in idx}) == len(idx) == 70                          # no crop twice
    assert {r[0] for r in idx} == {"sheet_00", "sheet_02"}                     # sheet_01 number is retired
    assert not (out / "sheet_01.png").exists()


def _holdout_pool(extra_game=True):
    rows, meta = [], []

    def add(prefix, n, **kw):
        for i in range(n):
            name = f"g1_{prefix}{i:04d}"
            rows.append(_pre(name, **kw)); meta.append({"name": name, "game": "g1"})
    add("r", 400, typ="Resonance"); add("a", 30, typ="Alignment"); add("s", 20, typ="Bubble", star=True)
    add("o", 2000, typ="Adjust")
    if extra_game:
        for i in range(100):
            rows.append(_pre(f"g2_x{i:03d}", "Resonance")); meta.append({"name": f"g2_x{i:03d}", "game": "g2"})
    return rows, meta


def _setup_holdout(d):
    rows, meta = _holdout_pool()
    _write_pre(d, rows)
    (d / "crops.jsonl").write_text("".join(json.dumps(m) + "\n" for m in meta), encoding="utf-8")


def test_holdout_stratified_and_deterministic(tmp_path):
    _setup_holdout(tmp_path)
    counts = rv.holdout(str(tmp_path), ["g1"], 1000)
    assert counts == {"Resonance": 250, "Alignment": 30, "star": 20, "fill": 700}
    out = tmp_path / "review" / "hold_g1"
    idx = _index(out / "index.tsv")
    assert len(idx) == 1000 and all(r[2].startswith("g1_") for r in idx)
    assert len({r[2] for r in idx}) == 1000
    assert sum(r[3] == "Resonance" for r in idx) >= 250
    first = (out / "index.tsv").read_text(encoding="utf-8")
    rv.holdout(str(tmp_path), ["g1"], 1000, force=True)
    assert (out / "index.tsv").read_text(encoding="utf-8") == first
    d2 = tmp_path / "second"
    _setup_holdout(d2)
    rv.main(["--holdout", "g1", "--n", "1000", "--dir", str(d2)])
    assert (d2 / "review" / "hold_g1" / "index.tsv").read_text(encoding="utf-8") == first


def test_holdout_refuses_recut_with_fixes(tmp_path):
    _setup_holdout(tmp_path)
    rv.holdout(str(tmp_path), ["g1"], 100)
    out = tmp_path / "review" / "hold_g1"
    (out / "fixes.tsv").write_text("sheet_00\tok\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rv.holdout(str(tmp_path), ["g1"], 100)
    assert (out / "fixes.tsv").exists()
    rv.holdout(str(tmp_path), ["g1"], 100, force=True)
    assert not (out / "fixes.tsv").exists() and (out / "fixes.tsv.old").exists()   # old ticks cannot mark new sheets


# ---- tag building ----

def _setup_tag(d, ticks=("sheet_00",), fixes=()):
    specs = [("g1", 1.0, i + 1, (0, 200, 0), {"buffed": i == 0}) for i in range(5)] + \
            [("g2", 1.0, i + 1, (0, 200, 0), {"glare": True}) for i in range(1)]
    names = _write_crops(d, specs)
    pre = [_pre(n, "Resonance", 1) for n in names]
    pre[3] = _pre(names[3], "?", 0)
    _write_pre(d, pre)
    out = d / "review" / "amb"
    out.mkdir(parents=True)
    shown = [("sheet_00", 0, 0), ("sheet_00", 1, 1), ("sheet_00", 2, 2), ("sheet_01", 0, 3), ("sheet_01", 1, 4)]
    (out / "index.tsv").write_text("".join(f"{s}\t{i}\t{names[k]}\t{pre[k]['type']}\t{pre[k]['pip']}\n"
                                           for s, i, k in shown), encoding="utf-8")
    (out / "fixes.tsv").write_text("".join(t + "\tok\n" for t in ticks) + "".join(f + "\n" for f in fixes),
                                   encoding="utf-8")
    return names


def test_build_tag_chk_fixes_and_report(tmp_path, capsys):
    names = _setup_tag(tmp_path, fixes=("sheet_00:1\tAlignment\t2", "sheet_00:2\tdrop", "sheet_01:1\tBubble\t3"))
    bt.main(["--tag", "t", "--dir", str(tmp_path)])
    z = np.load(tmp_path / "feats_t.npz")
    y, pip, grp, eff, chk = (np.load(tmp_path / f"{k}_t.npy", allow_pickle=True) for k in ("y", "pip", "grp", "eff", "chk"))
    got = list(z["names"])
    assert got == [names[0], names[1], names[4], names[5]]          # 2 dropped, 3 is "?"
    assert len(y) == len(pip) == len(grp) == len(eff) == len(chk) == 4
    assert list(y) == ["Resonance", "Alignment", "Bubble", "Resonance"]
    assert list(pip) == [1, 2, 3, 1]
    assert list(grp) == ["g1", "g1", "g1", "g2"]
    assert list(eff) == [True, False, False, True]                    # buffed / glare
    assert list(chk) == [True, True, False, False]                    # sheet_01 unticked (fix kept, chk false)
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("t 4 {") and "'Resonance': 2" in out[0]
    assert out[1:] == ["fix rate Resonance 2/3"]                       # 3 checked, 1 changed + 1 dropped


def test_build_tag_games_filter(tmp_path):
    _setup_tag(tmp_path)
    bt.main(["--tag", "t", "--games", "g2", "--dir", str(tmp_path)])
    assert list(np.load(tmp_path / "grp_t.npy")) == ["g2"]


def test_build_tag_ticked_label_is_the_shown_one(tmp_path):
    names = _setup_tag(tmp_path)
    # models retrained and pre-labels re-run after the review: crop 0 now reads Alignment pip 5
    pre = [_pre(n, "Resonance", 1) for n in names]
    pre[0] = _pre(names[0], "Alignment", 5)
    _write_pre(tmp_path, pre)
    bt.main(["--tag", "t", "--dir", str(tmp_path)])
    y = np.load(tmp_path / "y_t.npy", allow_pickle=True); pip = np.load(tmp_path / "pip_t.npy")
    chk = np.load(tmp_path / "chk_t.npy")
    assert (y[0], pip[0], chk[0]) == ("Resonance", 1, True)           # as shown on the ticked sheet
