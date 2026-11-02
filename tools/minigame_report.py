"""Hit rate and miss cause of the live gauge records (read-only).

    python tools/minigame_report.py [--profile gpg|ld] [--file data/minigame/gauges.jsonl]

Counts only records with execute true, manual false and cancel_test false (dry runs, the user's own stops and
the cancel check are left out). Without --profile every profile found is reported, one block each.
Never writes anything.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "data" / "minigame" / "gauges.jsonl"

HEAD_LINE = "{profile}: 게이지 {n}개 · 노랑 {y} ({pct}%) · 보라 {p} · 파랑 {b} · 바깥 {o}"
LATENCY_LINE = "지연: 중앙값 {med} ms, 범위 {lo}-{hi} ms"
LATENCY_NONE = "지연: 측정값 없음"
MISS_LINE = "빗나감: 빠름 {e} · 늦음 {l} (평균 {avg} ms)"
NO_RECORDS = "{profile}: 기록 없음"
ALL_PROFILES = "전체"
ZONE_PREFIX = {"노랑": "y", "보라": "p", "파랑": "b", "바깥": "o"}     # the start of minigame_bot.ZONE_NAMES values


def load_records(path):
    """Usable records of a jsonl file: execute, not manual, not cancel_test. A missing file gives []."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    recs = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("execute") is True and r.get("manual") is False \
                and r.get("cancel_test") is False:
            recs.append(r)
    return recs


def report_lines(profile, recs):
    if not recs:
        return [NO_RECORDS.format(profile=profile)]
    count = dict.fromkeys(ZONE_PREFIX.values(), 0)
    for r in recs:
        key = ZONE_PREFIX.get(str(r.get("zone", ""))[:2])
        if key:
            count[key] += 1
    n = len(recs)
    lines = [HEAD_LINE.format(profile=profile, n=n, y=count["y"], pct=f"{100.0 * count['y'] / n:.0f}",
                              p=count["p"], b=count["b"], o=count["o"])]
    ms = [r["latency_sample"] * 1000.0 for r in recs if isinstance(r.get("latency_sample"), (int, float))]
    lines.append(LATENCY_LINE.format(med=round(statistics.median(ms)), lo=round(min(ms)), hi=round(max(ms)))
                 if ms else LATENCY_NONE)
    # AI-NOTE: error_ms is signed (negative = stopped early). Early/late are counted over the misses only,
    # but the mean is over ALL records: it is the systematic bias the H5 runbook compares with the sim, and
    # a miss-only mean is +0 when every gauge hits and swings by one frame on a single miss.
    errs = [r["error_ms"] for r in recs if isinstance(r.get("error_ms"), (int, float))]
    miss = [r["error_ms"] for r in recs
            if r.get("zone", "")[:2] != "노랑" and isinstance(r.get("error_ms"), (int, float))]
    avg = statistics.fmean(errs) if errs else 0.0
    lines.append(MISS_LINE.format(e=sum(e < 0 for e in miss), l=sum(e > 0 for e in miss), avg=f"{avg:+.0f}"))
    return lines


def main(argv=None, out=print):
    ap = argparse.ArgumentParser(prog="minigame_report", description="Hit rate and miss cause of gauges.jsonl.")
    ap.add_argument("--profile", help="only this profile (gpg / ld)")
    ap.add_argument("--file", default=str(DEFAULT_FILE), help="records file (default data/minigame/gauges.jsonl)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    recs = load_records(a.file)
    if a.profile:
        recs = [r for r in recs if r.get("profile") == a.profile]
        groups = [(a.profile, recs)]
    else:
        names = sorted({r.get("profile") for r in recs if r.get("profile")})
        groups = [(p, [r for r in recs if r.get("profile") == p]) for p in names] or [(ALL_PROFILES, [])]
    for profile, rs in groups:
        for line in report_lines(profile, rs):
            out(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
