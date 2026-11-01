import importlib.util
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("run_all_tool", ROOT / "tools" / "run_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_supervisor_args():
    m = _load()
    assert m.supervisor_args(False) == ["--mode", "duo"]
    assert m.supervisor_args(True) == ["--mode", "gear"]


def test_header_texts():
    m = _load()
    assert m.header_text(False) == "두 봇 시작 (기어=LD 대변먹는자 · 서폿=구글 배속봇)"
    assert m.header_text(True) == "기어봇만 시작 (LD)"
    assert m.header_text(False, "A", "B") == "두 봇 시작 (기어=LD A · 서폿=구글 B)"


def test_names_from_duo_toml(tmp_path):
    m = _load()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "duo.toml").write_text('host = "H"\npartner = "P"\n', encoding="utf-8")
    assert m.load_names(str(tmp_path)) == ("H", "P")
    assert m.load_names(str(tmp_path / "none")) == ("대변먹는자", "배속봇")


def test_tags_per_log_file():
    m = _load()
    assert m.tag_for("20261101_1200_gear.log") == "기어"
    assert m.tag_for("20261101_1200_support.log") == "서폿"
    assert m.tag_for("20261101_1200_gear_2.log") == "기어"
    assert m.tag_for("20261101_1200_support_2.log") == "서폿"
    assert m.tag_for("discord_bot.log") == "디코"
    assert m.tag_for("supervisor.log") is None


def test_tail_specs_patterns(tmp_path):
    m = _load()
    specs = m.tail_specs(str(tmp_path))
    assert [t for _, t in specs] == ["기어", "서폿", "디코"]
    assert specs[0][0] == os.path.join(str(tmp_path), "bot_logs", "2*_gear*.log")
    assert not any(p.endswith("2*.log") for p, _ in specs)


def test_show_has_new_keys():
    m = _load()
    for k in ("invite", "초대", "start check", "시작 점검", "wrong deck", "restart"):
        assert k in m.SHOW
        assert m.shown(f"x {k} y")
    assert not m.shown("plain noise")


def test_import_starts_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("started a process")
    monkeypatch.setattr(subprocess, "Popen", boom)
    lock_before = os.path.exists(_load().LOCK)
    m = _load()
    assert os.path.exists(m.LOCK) == lock_before
