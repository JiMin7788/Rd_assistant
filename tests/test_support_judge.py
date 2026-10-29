import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("support_judge", ROOT / "tools" / "support_judge.py")
sj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sj)


def ms(m1=(True, 1820), m2=(True, 2710), m3=(True, 3880)):
    def one(v):
        reached, score = v
        return {"reached": reached, "late": False, "score": score, "shot": None}
    return {"m1": one(m1), "m2": one(m2), "m3": one(m3)}


def rec(gid="g", ok=True, **kw):
    r = {"game_id": gid, "mode": "play", "gates": {"type": True, "pip": True},
         "result": "game_over", "max_score": 4630, "scores_confirmed": 12,
         "milestones": ms() if ok else ms(m3=(False, None))}
    r.update(kw)
    return r


def five(passing):
    return [rec(f"g{i}", ok=i < passing) for i in range(5)]


def test_pass_4_of_5():
    lines, code = sj.judge(five(4))
    assert code == 0
    assert lines[-1] == "판정: 통과 — 5판 중 4판 달성 (4판 필요)"


@pytest.mark.parametrize("last", [0, -3])
def test_last_below_one_is_cannot_judge(last, capsys):
    lines, code = sj.judge(five(5), last)
    assert code == 2 and any(l.startswith("판정 불가") for l in lines)
    assert not any("통과" in l for l in lines)
    with pytest.raises(SystemExit) as e:
        sj.main(["--log", str(ROOT / "nonexistent.jsonl"), "--last", str(last)])
    assert e.value.code == 2
    assert "판정: 통과" not in capsys.readouterr().out


def test_zero_judged_games_cannot_judge():
    lines, code = sj.judge([], 5)
    assert code == 2 and lines[-1].startswith("판정 불가")


def test_missing_max_score_prints_question_mark():
    lines, _ = sj.judge([rec("g0", max_score=None)], 1)
    assert "최고 점수 ?" in lines[0] and "최고 점수 -" not in lines[0]


def test_fail_3_of_5():
    lines, code = sj.judge(five(3))
    assert code == 1
    assert lines[-1] == "판정: 실패 — 5판 중 3판 달성 (4판 필요)"


def test_cannot_judge():
    lines, code = sj.judge(five(5)[:3])
    assert code == 2
    assert lines[-1] == "판정 불가: 판정 대상 판이 3판뿐입니다 (5판 필요)"


def test_game_line_verbatim_and_variants():
    r = rec("sup20261102_201500")
    lines, _ = sj.judge([r] * 5)
    assert lines[0] == ("1. sup20261102_201500 · 최고 점수 4630 · 2000전 공명7≥1·정렬7≥1 O(1820)"
                        " · 3000전 공명7≥2·정렬7≥1 O(2710) · 4000전 완성 O(3880)"
                        " · 스크린샷 data/support_runs/sup20261102_201500/")
    late = rec("x", milestones={"m1": {"reached": True, "late": False, "score": 1, "shot": None},
                                "m2": {"reached": False, "late": True, "score": 3150, "shot": None},
                                "m3": {"reached": False, "late": False, "score": None,
                                       "shot": None}})
    line = sj._game_line(1, late)
    assert "3000전 공명7≥2·정렬7≥1 X(3150)" in line and "4000전 완성 X(-)" in line


def test_unconfirmed_scores_fail():
    bad = rec("bad", scores_confirmed=0)
    assert sj._game_line(1, bad).endswith(" · 점수 판독 실패")
    lines, code = sj.judge([bad] + [rec(f"g{i}") for i in range(3)] + [rec("h", ok=False)])
    assert code == 1 and lines[-1] == "판정: 실패 — 5판 중 3판 달성 (4판 필요)"


def test_exclusions():
    extra = [rec("c", mode="collect"), rec("t", mode="trial"),
             rec("p", gates={"type": True, "pip": False}), rec("m", result="moved")]
    lines, code = sj.judge(extra + five(5))
    assert lines[0] == "제외 4판 (수집 모드 1 · 게이트 미통과 2 · 비정상 종료 1)"
    assert code == 0
    assert all(not l.startswith(("c", "t", "p", "m")) or l[0].isdigit() for l in lines[1:-1])


def test_last_n_in_file_order():
    recs = [rec("old", ok=False)] + five(5)
    lines, code = sj.judge(recs)
    assert code == 0 and "old" not in "\n".join(lines)


def test_last_10_needs_8():
    recs = [rec(f"g{i}", ok=i < 8) for i in range(10)]
    assert sj.judge(recs, last=10)[0][-1] == "판정: 통과 — 10판 중 8판 달성 (8판 필요)"
    recs = [rec(f"g{i}", ok=i < 7) for i in range(10)]
    lines, code = sj.judge(recs, last=10)
    assert code == 1 and lines[-1] == "판정: 실패 — 10판 중 7판 달성 (8판 필요)"


def test_power_key_ignored():
    base = five(4)
    with_power = [dict(r, power={"growth": 7}) for r in base]
    null_power = [dict(r, power=None) for r in base]
    assert sj.judge(with_power) == sj.judge(base) == sj.judge(null_power)


def test_no_module_side_effects():
    tree = ast.parse((ROOT / "tools" / "support_judge.py").read_text(encoding="utf-8"))
    for node in tree.body:
        assert not isinstance(node, ast.Expr) or isinstance(node.value, ast.Constant)
        if isinstance(node, ast.If):
            assert "__main__" in ast.dump(node.test)
