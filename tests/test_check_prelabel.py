import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_prelabel", ROOT / "tools" / "check_prelabel.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def _files(tmp_path, truth, pred):
    (tmp_path / "eval.tsv").write_text("".join(f"{n}\t{t}\n" for n, t in truth.items()), encoding="utf-8")
    (tmp_path / "pre.jsonl").write_text("".join(json.dumps({"name": n, "type": t}) + "\n" for n, t in pred.items()),
                                        encoding="utf-8")
    return str(tmp_path / "eval.tsv"), str(tmp_path / "pre.jsonl")


def test_precision_recall_and_unknown_share(tmp_path, capsys):
    truth = {"a": "Resonance", "b": "Resonance", "c": "Resonance", "d": "Alignment", "e": "Alignment"}
    pred = {"a": "Resonance", "b": "Resonance", "c": "?", "d": "Resonance", "e": "Alignment", "extra": "Bubble"}
    cp.main(_files(tmp_path, truth, pred))
    out = capsys.readouterr().out.splitlines()
    assert "Resonance: precision 0.667 (2/3) recall 0.667 (2/3)" in out
    assert "Alignment: precision 1.000 (1/1) recall 0.500 (1/2)" in out
    assert any(l.startswith("?: share 0.200 (1/5)") for l in out)


def test_missing_crops_are_reported_not_counted(tmp_path, capsys):
    cp.main(_files(tmp_path, {"a": "Resonance", "b": "Alignment"}, {"a": "Resonance"}))
    out = capsys.readouterr().out
    assert "Resonance: precision 1.000 (1/1) recall 1.000 (1/1)" in out
    assert "missing from pre-labels: 1 crop(s), e.g. b" in out


def test_score_without_predictions_is_nan():
    res, unk, missing = cp.score({"a": "Resonance"}, {"a": "?"})
    assert res["Resonance"][0] != res["Resonance"][0] and res["Resonance"][3] == 0 and unk == 1.0 and missing == []
