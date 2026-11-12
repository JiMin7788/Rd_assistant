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
    assert m.header_text(False) == "두 봇 시작 (기어1=구글 대변먹는자 · 서폿=구글 배속봇)"
    assert m.header_text(True) == "기어봇만 시작 (구글)"
    assert m.header_text(False, "A", "B") == "두 봇 시작 (기어1=구글 A · 서폿=구글 B)"


def test_names_from_duo_toml(tmp_path):
    m = _load()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "duo.toml").write_text('host = "H"\npartner = "P"\n', encoding="utf-8")
    assert m.load_names(str(tmp_path)) == ("H", "P")
    assert m.load_names(str(tmp_path / "none")) == ("대변먹는자", "배속봇")


def test_tags_per_log_file():
    m = _load()
    assert m.tag_for("20261101_1200_gpg.log") == "기어1"
    assert m.tag_for("20261101_1200_gpg2.log") == "서폿"
    assert m.tag_for("20261101_1200_gpg_2.log") == "기어1"
    assert m.tag_for("20261101_1200_gpg2_2.log") == "서폿"
    assert m.tag_for("discord_bot.log") == "디코"
    assert m.tag_for("supervisor.log") is None


def test_tail_specs_patterns(tmp_path):
    m = _load()
    specs = m.tail_specs(str(tmp_path))
    assert [t for _, t in specs] == ["기어1", "서폿", "디코"]
    assert specs[0][0] == os.path.join(str(tmp_path), "bot_logs", "2*_gpg[_.]*")
    assert not any(p.endswith("2*.log") for p, _ in specs)


def test_show_has_new_keys():
    m = _load()
    for k in ("invite", "초대", "start check", "시작 점검", "wrong deck", "restart"):
        assert k in m.SHOW
        assert m.shown(f"x {k} y")
    assert not m.shown("plain noise")


def test_solo_banner_from_bot_mode(tmp_path):
    import json
    m = _load()
    assert m.solo_banner(str(tmp_path)) is None                       # supervisor has not decided yet
    p = tmp_path / "bot_mode.json"
    p.write_text(json.dumps({"mode": "duo", "bots": []}), encoding="utf-8")
    assert m.solo_banner(str(tmp_path)) is None
    p.write_text(json.dumps({"mode": "solo", "bots": [], "solo": {"profile": "gpg2", "name": "배속봇",
                                                                  "partner": "대변먹는자"}}), encoding="utf-8")
    assert m.solo_banner(str(tmp_path)) == "▶ 한 창 모드: 배속봇 혼자 -- 대변먹는자 초대"


def test_main_prints_the_solo_banner_once(tmp_path, monkeypatch, capsys):
    """main with --no-game and every outside effect faked: the console shows the solo line once."""
    import json
    m = _load()
    (tmp_path / "bot_logs").mkdir()
    (tmp_path / "bot_mode.json").write_text(json.dumps(
        {"mode": "solo", "bots": [], "solo": {"profile": "gpg", "name": "대변먹는자", "partner": "배속봇"}}),
        encoding="utf-8")
    monkeypatch.setattr(m, "DATA", str(tmp_path))
    monkeypatch.setattr(m, "LOCK", str(tmp_path / "run_all.pid"))
    monkeypatch.setattr(m, "solo_banner", lambda data_dir=str(tmp_path), _f=m.solo_banner: _f(data_dir))
    monkeypatch.setattr(m, "tail_specs", lambda data_dir=None: [])
    monkeypatch.setattr(m.os, "system", lambda c: 0)

    class Disc:
        returncode = None
        def poll(self): return None
        def terminate(self): pass
    monkeypatch.setattr(m, "start", lambda *a, **k: Disc())
    n = [0]
    def sleep(s):
        n[0] += 1
        if n[0] >= 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(m.time, "sleep", sleep)
    assert m.main(["--no-game"]) == 0
    assert capsys.readouterr().out.count("▶ 한 창 모드: 대변먹는자 혼자 -- 배속봇 초대") == 1


def test_import_starts_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("started a process")
    monkeypatch.setattr(subprocess, "Popen", boom)
    lock_before = os.path.exists(_load().LOCK)
    m = _load()
    assert os.path.exists(m.LOCK) == lock_before
