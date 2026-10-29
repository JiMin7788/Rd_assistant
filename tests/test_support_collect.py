import json

import cv2
import numpy as np

from rdom.capture.live import rects_cover
from rdom.perception import collect

CONTENT = (100, 100, 500, 900)


def test_rects_cover_cases():
    assert rects_cover(CONTENT, [(0, 0, 101, 101)])
    assert rects_cover(CONTENT, [(300, 300, 400, 400)])
    assert not rects_cover(CONTENT, [(0, 0, 100, 900)])      # touching left edge
    assert not rects_cover(CONTENT, [(500, 100, 600, 900)])  # touching right edge
    assert not rects_cover(CONTENT, [(600, 0, 700, 50)])
    assert not rects_cover(CONTENT, [])


def _frame():
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (1280, 720, 3), dtype=np.uint8)


def test_save_support_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path))
    gid = "sup20261101_120000"
    collect.save_support_cells(_frame(), gid, 15.0, True, buffed={3}, glare=False)
    raw = sorted((tmp_path / "_raw").glob("*.png"))
    hi = sorted((tmp_path / "_hires").glob("*.png"))
    assert [p.name for p in raw] == [f"{gid}_15.0_{i:02d}.png" for i in range(1, 16)]
    assert len(hi) == 15
    assert cv2.imread(str(raw[0])).shape[:2] == (72, 72)
    assert cv2.imread(str(hi[0])).shape[:2] == (128, 128)
    rows = [json.loads(x) for x in (tmp_path / "crops.jsonl").read_text().splitlines()]
    assert len(rows) == 15
    assert set(rows[0]) == {"name", "game", "t", "cell", "buffed", "glare"}
    assert [r["cell"] for r in rows if r["buffed"]] == [3]
    assert not any(r["glare"] for r in rows)


def test_covered_writes_nothing_and_rate_limits_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(collect, "SUPPORT_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(collect, "_covered_logged", [-1e9])
    clock = [1000.0]
    monkeypatch.setattr(collect.time, "monotonic", lambda: clock[0])
    out = tmp_path / "f" / "a.png"
    for _ in range(3):
        collect.save_support_cells(_frame(), "g", 1.0, False)
        assert collect.save_frame(_frame(), out, False) is None
        clock[0] += 10
    assert capsys.readouterr().out.count("frame not saved: game window covered") == 1
    clock[0] += 60
    collect.save_frame(_frame(), out, False)
    assert capsys.readouterr().out.count("frame not saved: game window covered") == 1
    assert not (tmp_path / "s").exists() and not (tmp_path / "f").exists()


def test_save_frame(tmp_path):
    f = _frame()
    p = tmp_path / "a" / "b" / "x.png"
    assert collect.save_frame(f, p, True) == p
    assert np.array_equal(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB), f)
    assert collect.save_frame(None, tmp_path / "y.png", True) is None
    assert collect.save_frame(f, tmp_path / "z.txt", True) is None   # cv2 cannot encode
