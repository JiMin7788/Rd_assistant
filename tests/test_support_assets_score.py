import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import board, digits, score

ROOT = Path(__file__).resolve().parents[1]
BOX = (0.30, 0.02, 0.70, 0.08)
H = 1280
W = round(H * 9 / 16)
BOX_PX = (int(BOX[0] * W), int(BOX[1] * H), int(BOX[2] * W), int(BOX[3] * H))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def render(text):
    x0, y0, x1, y1 = BOX_PX
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 3, cv2.LINE_AA)
    return img


@pytest.fixture
def env(tmp_path, monkeypatch):
    tools = load("build_digit_templates")
    cs = load("check_support_assets")
    sdir = tmp_path / "data" / "digits" / "score_v2"
    sdir.mkdir(parents=True)
    for i, n in enumerate(["61937", "40528"]):
        cv2.imwrite(str(sdir / f"{n}_{i}.png"), render(n))
    out = tmp_path / "tpl"
    out.mkdir()
    assert tools.build_kind("score", str(sdir), out=str(out)) == []
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})
    monkeypatch.setattr(score, "SCORE_BOX", BOX)
    return cs, tmp_path / "data", sdir


def test_check_score_counts_correct_none_wrong(env):
    cs, data, sdir = env
    cv2.imwrite(str(sdir / "30475_a.png"), render("30475"))          # correct
    cv2.imwrite(str(sdir / "30476_b.png"), render("30475"))          # label differs from the read: wrong
    cv2.imwrite(str(sdir / "30475_c.png"), np.full_like(render("1"), 255))   # unreadable: none
    assert cs.check_score(str(data)) == "score: n=5 correct=3 none=1 wrong=1"


def test_check_score_skips_bad_files(env):
    cs, data, sdir = env
    (sdir / "123_empty.png").write_bytes(b"")
    cv2.imwrite(str(sdir / "abc_1.png"), render("1820"))
    assert cs.check_score(str(data)) == "score: n=2 correct=2 none=0 wrong=0"


def test_check_score_lobby_counts_only_non_battle(env, monkeypatch):
    cs, data, _ = env
    man = data / "support_frames" / "manual"
    man.mkdir(parents=True)
    cv2.imwrite(str(man / "lobby.png"), np.zeros((H, W, 3), np.uint8))
    cv2.imwrite(str(man / "battle.png"), np.full((H, W, 3), 7, np.uint8))
    (man / "bad.png").write_bytes(b"")
    monkeypatch.setattr(board, "is_battle", lambda f: int(f[0, 0, 0]) == 7)
    assert cs.check_score_lobby(str(data)) == "score lobby: none=1/1"


def test_check_score_lobby_counts_a_read(env, monkeypatch):
    cs, data, _ = env
    man = data / "support_frames" / "manual"
    man.mkdir(parents=True)
    cv2.imwrite(str(man / "lobby.png"), np.zeros((H, W, 3), np.uint8))
    monkeypatch.setattr(board, "is_battle", lambda f: False)
    monkeypatch.setattr(score, "read_score", lambda f: 1820)
    assert cs.check_score_lobby(str(data)) == "score lobby: none=0/1"


@pytest.mark.parametrize("sub", ["empty", "missing"])
def test_main_without_inputs_prints_zero_lines(env, tmp_path, capsys, sub):
    cs, _, _ = env
    d = tmp_path / sub
    if sub == "empty":
        d.mkdir()
    ov = tmp_path / "ov"
    assert cs.main(["--data-dir", str(d), "--out-dir", str(ov)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "score: n=0 correct=0 none=0 wrong=0", "score lobby: none=0/0",
        "deck bar: support 0/0 gear-false 0/0", "deck bar excluded: 0",
        "power cards: 0/0", f"lv box: drew 0 overlays to {ov}",
        "sp: n=0 correct=0 none=0 wrong=0", "summon cost: n=0 correct=0 none=0 wrong=0",
        "panel sp: n=0 correct=0 none=0 wrong=0", "price: n=0 correct=0 none=0 wrong=0",
        "power level: n=0 correct=0 none=0 wrong=0"]


def test_main_default_out_dir_is_support_frames_check(env, tmp_path, capsys):
    cs, _, _ = env
    d = tmp_path / "empty_data"
    d.mkdir()
    assert cs.main(["--data-dir", str(d)]) == 0
    expected = d / "support_frames" / "_check"
    assert capsys.readouterr().out.splitlines()[-6] == f"lv box: drew 0 overlays to {expected}"


def test_main_exit_1_on_exception(env, monkeypatch, capsys):
    cs, data, _ = env
    monkeypatch.setattr(cs, "check_score", lambda d: 1 / 0)
    assert cs.main(["--data-dir", str(data)]) == 1


def test_committed_template_shape():
    T = np.load(ROOT / "assets" / "templates" / "digits_score.npz")["T"]
    assert T.shape == (10, digits.GH, digits.GW)
