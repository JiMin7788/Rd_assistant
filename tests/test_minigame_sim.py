"""tests/test_minigame_sim.py -- the gauge sim (regression check of our own game model) and tools/minigame_report.py.

The sim says nothing about the real game (spec R11). Everything runs on a virtual clock; the report tests
write jsonl files into tmp dirs only (never C:/dev/rdom/data).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bot = _load("minigame_bot_sim_under_test", "minigame_bot.py")
report = _load("minigame_report_under_test", "minigame_report.py")

from rdom.sim.gauge_sim import CASES, SimGame, run_case  # noqa: E402

SEED = 1
GAUGES = {"gpg": 104, "ld60": 16, "ld30": 16, "ld60swipe": 16}
_RUNS = {}


def sim(case):
    if case not in _RUNS:
        _RUNS[case] = run_case(bot, case, GAUGES[case], SEED)
    return _RUNS[case]


# ---------------------------------------------------------------- the sim
def test_gpg_case_is_yellow_in_98_of_100_after_the_first_four():
    c = CASES["gpg"]
    assert (c.fps, c.press_lead, c.latency, c.jitter, c.guess) == (60.0, 0.25, 0.045, 0.003, 0.060)
    run = sim("gpg")
    assert len(run.results) == 104
    assert run.yellow(5, 104) >= 98
    assert not any(r["manual"] for r in run.results[4:]), "the bot left a gauge to the sim's manual timeout"


@pytest.mark.parametrize("case", ["gpg", "ld60", "ld30", "ld60swipe"])
def test_no_action_is_planned_in_the_past_or_sent_late(case):
    run = sim(case)
    kind = "spawn" if run.case.swipe else "down"
    acts = [a for a in run.actions if a["kind"] == kind]
    assert acts, "the loop never sent a DOWN / swipe"
    for a in acts:
        assert a["planned"] is not None and a["scheduled"] is not None
        assert a["scheduled"] >= a["planned"], a
        assert a["sent"] - a["scheduled"] <= 0.002, a


def test_the_loop_starts_from_the_wrong_guess_and_the_sim_is_deterministic():
    run = sim("gpg")
    assert run.cal.default == 0.060 and run.cal.samples
    again = run_case(bot, "gpg", 6, SEED)
    assert [r["zone"] for r in again.results] == [r["zone"] for r in run.results[:6]]


def test_game_frame_stop_and_zone_come_from_the_true_tip():
    g = SimGame(3, 60.0, 0.03, 0.045, 0.0)
    first = g.gauges[0]
    arrival = g.frame_time(first.k_start + 10) - 1e-4
    assert g.register_stop(arrival)
    assert first.stop_k == first.k_start + 10
    assert g.results[0]["zone"] == g.zone(first, g.tip(first, first.stop_k))
    assert not g.register_stop(arrival + 1.0)             # a second UP on a stopped gauge does nothing
    assert g.gauges[-1].t_start >= g.frame_time(first.stop_k) + g.GAP_S


# ---------------------------------------------------------------- tools/minigame_report.py
def _rec(**kw):
    r = {"profile": "gpg", "execute": True, "manual": False, "cancel_test": False, "zone": "노랑 (완벽해)",
         "latency_sample": 0.050, "error_ms": 0.0}
    r.update(kw)
    return r


def _write(path, recs):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")


def _run(*args):
    out = []
    assert report.main(list(args), out=out.append) == 0
    return out


def test_report_prints_the_three_lines(tmp_path):
    f = tmp_path / "gauges.jsonl"
    _write(f, [_rec(latency_sample=0.040), _rec(latency_sample=0.050), _rec(latency_sample=0.060),
               _rec(zone="보라 (쿨)", latency_sample=0.070, error_ms=-12.0),
               _rec(zone="파랑 (나이스)", latency_sample=0.080, error_ms=30.0),
               _rec(zone="바깥", latency_sample=0.090, error_ms=40.0)])
    assert _run("--profile", "gpg", "--file", str(f)) == [
        "gpg: 게이지 6개 · 노랑 3 (50%) · 보라 1 · 파랑 1 · 바깥 1",
        "지연: 중앙값 65 ms, 범위 40-90 ms",
        "빗나감: 빠름 1 · 늦음 2 (전체 평균 +10 ms)"]


def test_report_mean_error_covers_hits_too(tmp_path):
    f = tmp_path / "gauges.jsonl"
    _write(f, [_rec(error_ms=10.0), _rec(error_ms=14.0)])
    assert _run("--profile", "gpg", "--file", str(f))[2] == "빗나감: 빠름 0 · 늦음 0 (전체 평균 +12 ms)"


def test_report_ignores_manual_dry_run_cancel_test_and_other_profiles(tmp_path):
    f = tmp_path / "gauges.jsonl"
    _write(f, [_rec(), _rec(manual=True, zone="바깥", error_ms=99.0), _rec(execute=False, zone="바깥"),
               _rec(cancel_test=True, zone="바깥"), _rec(profile="ld", zone="바깥")])
    assert _run("--profile", "gpg", "--file", str(f)) == [
        "gpg: 게이지 1개 · 노랑 1 (100%) · 보라 0 · 파랑 0 · 바깥 0",
        "지연: 중앙값 50 ms, 범위 50-50 ms",
        "빗나감: 빠름 0 · 늦음 0 (전체 평균 +0 ms)"]


def test_report_without_records_says_so_and_writes_nothing(tmp_path):
    f = tmp_path / "gauges.jsonl"
    _write(f, [_rec(manual=True), _rec(execute=False)])
    before = f.read_bytes()
    assert _run("--profile", "gpg", "--file", str(f)) == ["gpg: 기록 없음"]
    assert _run("--profile", "ld", "--file", str(f)) == ["ld: 기록 없음"]
    assert _run("--profile", "gpg", "--file", str(tmp_path / "missing.jsonl")) == ["gpg: 기록 없음"]
    assert not (tmp_path / "missing.jsonl").exists() and f.read_bytes() == before


def test_report_default_file_is_the_live_record_file():
    assert report.DEFAULT_FILE == ROOT / "data" / "minigame" / "gauges.jsonl"


def test_every_sim_gauge_yellow_is_2_5_to_3_5_percent_of_travel():
    game = SimGame(SEED, 60.0, 0.03, 0.045, 0.003)
    for _ in range(199):
        game._new_gauge(1000.0)
    travel = SimGame.HI - SimGame.LO
    assert len(game.gauges) == 200
    for g in game.gauges:
        assert 0.025 <= g.yw / travel <= 0.035
