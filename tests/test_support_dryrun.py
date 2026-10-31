import ast
import importlib.util
import os

import numpy as np
import pytest

from rdom.perception import support

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "support_dryrun.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("support_dryrun", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def empty_data(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "_DATA", str(tmp_path))
    monkeypatch.setattr(support, "_models", {})


def test_dryrun_without_models(empty_data):
    frame = np.zeros((1280, 720, 3), np.uint8)
    lines = load_tool().dryrun(frame)
    assert len(lines) == 8
    for r in range(3):
        cells = lines[r].split("  ")
        assert cells == [f"#{r * 5 + i} junk 0" for i in range(1, 6)]
    assert lines[3].startswith("evaluate: {") and "'unknown': 15" in lines[3]
    assert lines[4].startswith("planned action: {'op': 'wait'")
    assert lines[5] == "score: None"
    assert lines[6] == "sp: None" and lines[7] == "summon cost: None"


def test_main_reads_png(empty_data, tmp_path, capsys):
    from PIL import Image
    p = tmp_path / "f.png"
    Image.fromarray(np.zeros((1280, 720, 3), np.uint8)).save(p)
    assert load_tool().main([str(p)]) == 0
    assert "score: None" in capsys.readouterr().out


USAGE = "usage: python tools/support_dryrun.py [--data-dir <dir>] <frame.png>"


def test_usage_text_and_exit_codes(capsys):
    tool = load_tool()
    for argv, code in ((["--help"], 0), (["-h"], 0), ([], 2), (["a", "b"], 2), (["--data-dir", "x"], 2)):
        assert tool.main(argv) == code
        assert capsys.readouterr().out.strip() == USAGE


def test_data_dir_sets_model_dirs(tmp_path, monkeypatch, capsys):
    from PIL import Image
    from rdom.perception import gear
    monkeypatch.setattr(support, "_DATA", "old")      # monkeypatch restores both after main() overwrites them
    monkeypatch.setattr(gear, "_DATA", "old")
    monkeypatch.setattr(support, "_models", dict(stale=1))
    p = tmp_path / "f.png"
    Image.fromarray(np.zeros((1280, 720, 3), np.uint8)).save(p)
    d = tmp_path / "models"
    d.mkdir()
    assert load_tool().main(["--data-dir", str(d), str(p)]) == 0
    assert support._DATA == str(d) and gear._DATA == str(d) and "stale" not in support._models
    out = capsys.readouterr().out
    assert "sp: None" in out and "summon cost: None" in out


def test_no_injection_import():
    src = open(TOOL, encoding="utf-8").read()
    assert "Injector" not in src
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom):
            assert "inject" not in (n.module or "")
        if isinstance(n, ast.Import):
            assert all("inject" not in a.name for a in n.names)
