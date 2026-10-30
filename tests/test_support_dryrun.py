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


def test_no_injection_import():
    src = open(TOOL, encoding="utf-8").read()
    assert "Injector" not in src
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom):
            assert "inject" not in (n.module or "")
        if isinstance(n, ast.Import):
            assert all("inject" not in a.name for a in n.names)
