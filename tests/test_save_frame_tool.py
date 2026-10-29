import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("save_frame_tool", ROOT / "tools" / "save_frame.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _claim(mod, folder, stamp, data):
    path, f = mod.claim_file(folder, stamp)
    with f:
        f.write(data)
    return path


def test_claim_never_overwrites(tmp_path):
    mod = _load()
    p1 = _claim(mod, tmp_path, "20261029_120000", b"one")
    p2 = _claim(mod, tmp_path, "20261029_120000", b"two")
    p3 = _claim(mod, tmp_path, "20261029_120000", b"three")
    assert [p.name for p in (p1, p2, p3)] == ["20261029_120000.png", "20261029_120000_2.png", "20261029_120000_3.png"]
    assert p1.read_bytes() == b"one"
    assert p2.read_bytes() == b"two"


def test_claim_skips_precreated_suffix(tmp_path):
    mod = _load()
    (tmp_path / "s.png").write_bytes(b"a")
    (tmp_path / "s_2.png").write_bytes(b"b")   # as if another process claimed it
    p = _claim(mod, tmp_path, "s", b"c")
    assert p.name == "s_3.png"
    assert (tmp_path / "s_2.png").read_bytes() == b"b"


def test_claim_exhausted_returns_none(tmp_path):
    mod = _load()
    (tmp_path / "s.png").write_bytes(b"")
    for n in range(2, 100):
        (tmp_path / f"s_{n}.png").write_bytes(b"")
    assert mod.claim_file(tmp_path, "s") is None


def test_run_all_show_has_memory_lines():
    text = (ROOT / "tools" / "run_all.py").read_text(encoding="utf-8")
    assert '"unreadable"' in text and '"board changed without our action"' in text
