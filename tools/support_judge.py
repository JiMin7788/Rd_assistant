"""Judge the support-deck acceptance (m1/m2/m3 reached in 4 of the last 5 games) from the round log.

    python tools/support_judge.py [--log data/support_rounds.jsonl] [--last 5]

Exit code: 0 pass, 1 fail, 2 cannot judge. Pure core: judge(records, last) -> (lines, exit_code).
"""
import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "data" / "support_rounds.jsonl"

# (key in record, label) per milestone
LABELS = (("m1", "2000전 공명7≥1·정렬7≥1"), ("m2", "3000전 공명7≥2·정렬7≥1"),
          ("m3", "4000전 완성"))


def _exclusion(rec):
    """None when eligible, else the reason bucket."""
    mode = rec.get("mode")
    if mode == "collect":
        return "collect"
    gates = rec.get("gates") or {}
    if mode != "play" or not (gates.get("type") and gates.get("pip")):
        return "gate"
    return None if rec.get("result") == "game_over" else "abnormal"


def _passed(rec):
    ms = rec.get("milestones") or {}
    return (bool(rec.get("scores_confirmed")) and rec["scores_confirmed"] > 0
            and all((ms.get(k) or {}).get("reached") for k, _ in LABELS))


def _mark(m):
    m = m or {}
    score = m.get("score")
    if m.get("reached"):
        return f"O({'?' if score is None else score})"
    if m.get("late"):
        return f"X({'-' if score is None else score})"
    return "X(-)"


def _game_line(i, rec):
    ms = rec.get("milestones") or {}
    gid = rec.get("game_id")
    best = rec.get("max_score")
    parts = [f"{i}. {gid}", f"최고 점수 {'-' if best is None else best}"]
    parts += [f"{label} {_mark(ms.get(k))}" for k, label in LABELS]
    parts.append(f"스크린샷 data/support_runs/{gid}/")
    line = " · ".join(parts)
    if not rec.get("scores_confirmed"):
        line += " · 점수 판독 실패"
    return line


def judge(records, last=5):
    lines = []
    eligible = []
    excluded = {"collect": 0, "gate": 0, "abnormal": 0}
    for rec in records:
        why = _exclusion(rec)
        if why is None:
            eligible.append(rec)
        else:
            excluded[why] += 1
    total_ex = sum(excluded.values())
    if total_ex:
        lines.append(f"제외 {total_ex}판 (수집 모드 {excluded['collect']} · "
                     f"게이트 미통과 {excluded['gate']} · 비정상 종료 {excluded['abnormal']})")
    chosen = eligible[-last:] if last > 0 else []
    for i, rec in enumerate(chosen, 1):
        lines.append(_game_line(i, rec))
    if len(chosen) < last:
        lines.append(f"판정 불가: 판정 대상 판이 {len(chosen)}판뿐입니다 ({last}판 필요)")
        return lines, 2
    need = math.ceil(0.8 * last)
    got = sum(1 for rec in chosen if _passed(rec))
    ok = got >= need
    lines.append(f"판정: {'통과' if ok else '실패'} — {last}판 중 {got}판 달성 ({need}판 필요)")
    return lines, 0 if ok else 1


def load_records(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--last", type=int, default=5)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        records = load_records(args.log)
    except OSError as e:
        print(f"판정 불가: 로그를 읽을 수 없습니다 ({e})")
        return 2
    lines, code = judge(records, args.last)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
