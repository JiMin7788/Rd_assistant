import contextlib
import importlib.util
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "tools"))
    return mod


def _h5():
    todo = (ROOT / "CLAUDE_CODE_TODO.md").read_text(encoding="utf-8")
    assert "### H5 — 미니게임 게이지 봇 (rdF05)" in todo
    return re.split(r"\n#{2,3} ", todo.split("### H5 — 미니게임 게이지 봇 (rdF05)")[1])[0]


def test_h5_section_has_four_steps_and_checks():
    h5 = _h5()
    for n in "1234":
        assert "(" + n + ")" in h5, n
    for s in ("취소 점검", "취소 점검: 삼각형이 계속 움직여요 (정상)", "⚠ 취소 점검", "[드라이런]", "지연 보정", "저장값",
              "20 ms", "8 ms", "ld60swipe", "19", "20게이지", "회귀", "티켓", "협동 봇", "Ctrl+C", "⛔"):
        assert s in h5, s


def test_h5_commands_and_flags_exist_in_argparse():
    h5 = _h5()
    bot = _load("minigame_bot")
    bot_flags = {o for a in bot.build_parser()._actions for o in a.option_strings}
    buf = io.StringIO()
    report = _load("minigame_report")
    with contextlib.redirect_stdout(buf):
        report.main(["--help"])
    report_help = buf.getvalue()
    assert (ROOT / "tools" / "minigame_bot.py").is_file() and "tools/minigame_bot.py" in h5
    assert (ROOT / "tools" / "minigame_report.py").is_file() and "tools/minigame_report.py" in h5
    for flag in ("--profile", "--execute", "--probe-input", "--cancel-test"):
        assert flag in h5, flag
        assert flag in bot_flags, flag
    assert "--profile" in report_help
    # every flag in the runbook belongs to one of the two tools
    for flag in set(re.findall(r"--[a-z][a-z-]*", h5)):
        assert flag in bot_flags or flag in report_help, flag


def test_spec_has_minigame_section():
    spec = (ROOT / "docs" / "01_GAME_SPEC.md").read_text(encoding="utf-8")
    sec = spec.split("## 미니게임 — 군밀 대청소")[1].split("\n## ")[0]
    for s in ("2 gauges per run", "UP", "random", "no time limit", "완벽해", "쿨", "나이스"):
        assert s in sec, s
