import hashlib
import importlib.util
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from rdom.perception import digits, gear, support

H = 1280
W = round(H * 9 / 16)


def noise(h, w, seed):
    return np.random.RandomState(seed).randint(0, 256, (h, w, 3)).astype(np.uint8)


def save_rgb(path, img):
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))


@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(support, "_DATA", str(d))
    monkeypatch.setattr(support, "_models", {})
    return d


@pytest.fixture
def tpl(tmp_path, monkeypatch):
    d = tmp_path / "tpl"
    d.mkdir()
    monkeypatch.setattr(support, "_TPL", str(d))
    monkeypatch.setattr(support, "_models", {})
    return d


def touch(d, names):
    for n in names:
        (d / n).write_bytes(n.encode())


def logits_for_pips(pips):
    return np.array([np.where(gear.PIP_PATTERNS[p - 1] > 0, 8.0, -8.0) for p in pips], np.float32)


def fake_loader(monkeypatch, nets):
    """Replace support._load_net; nets: basename -> callable(x, t). Returns the (basename, n_out) log."""
    log = []

    def load(path, n_out):
        log.append((os.path.basename(path), n_out))
        return nets[os.path.basename(path)]
    monkeypatch.setattr(support, "_load_net", load)
    return log


def type_net(classes):
    """Fake type net: crop i gets class classes[i] (rest 'empty')."""
    def net(x, t):
        z = np.full((len(x), len(support.SUPPORT_CLASSES)), -10.0, np.float32)
        for i in range(len(x)):
            z[i, support.SUPPORT_CLASSES.index(classes[i] if i < len(classes) else "empty")] = 10.0
        return z
    return net


def pip_net(pips):
    return lambda x, t: logits_for_pips((list(pips) + [1] * len(x))[:len(x)])


def star_net(probs):
    z = np.log(np.array(probs) / (1 - np.array(probs)))[:, None].astype(np.float32)
    return lambda x, t: z[:len(x)]


BLANK = np.zeros((H, W, 3), np.uint8)


# ---- AC1 / AC2 / AC3 ----

def test_classes():
    assert support.SUPPORT_CLASSES == ("Resonance", "Alignment", "Bubble", "Adjust", "Growth", "Joker",
                                       "empty", "junk", "Crystal", "Bomb")


def test_load_net_uses_gear_pipnet_with_n_out(tmp_path):
    import torch
    net = gear._pipnet_cls()(n_out=len(support.SUPPORT_CLASSES))
    p = tmp_path / "t.pt"
    torch.save(net.state_dict(), p)
    loaded = support._load_net(str(p), len(support.SUPPORT_CLASSES))
    assert type(loaded).__name__ == "PipNet"
    out = loaded(torch.zeros(2, 3, 64, 64), torch.zeros(2, dtype=torch.long))
    assert tuple(out.shape) == (2, len(support.SUPPORT_CLASSES))


def test_no_type_file_all_junk(data):
    out = support.read_board_support(BLANK)
    assert [d["cell"] for d in out] == list(range(1, 16))
    for d in out:
        assert set(d) == {"cell", "type", "variant", "pip", "conf"}
        assert d["type"] == "junk" and d["pip"] == 0


def test_types_map_and_pip_zero(data, monkeypatch):
    touch(data, [support.TYPE_FILE] + list(support.PIP_FILES))
    classes = [support.SUPPORT_CLASSES[i % 10] for i in range(15)]
    nets = {support.TYPE_FILE: type_net(classes)}
    nets.update({f: pip_net([3] * 15) for f in support.PIP_FILES})
    log = fake_loader(monkeypatch, nets)
    calls = iter(range(100))
    monkeypatch.setattr(gear, "is_bomb", lambda c: next(calls) == 9)    # cell 10 (class Bomb) is a real bomb
    out = support.read_board_support(BLANK)
    assert (support.TYPE_FILE, 10) in log
    for i, d in enumerate(out):
        want = classes[i]
        if want == "Bomb" and i != 9:
            want = "junk"
        if i == 9:
            want = "Bomb"
        assert d["type"] == want
        assert d["pip"] == (0 if want in ("empty", "junk", "Crystal", "Bomb") else 3)
    # cell 10 is a CNN-Bomb and is_bomb holds -> Bomb; no other Bomb survives
    assert [d["cell"] for d in out if d["type"] == "Bomb"] == [10]


def test_cnn_bomb_becomes_junk_without_is_bomb(data, monkeypatch):
    touch(data, [support.TYPE_FILE])
    fake_loader(monkeypatch, {support.TYPE_FILE: type_net(["Bomb"] * 15)})
    monkeypatch.setattr(gear, "is_bomb", lambda c: False)
    assert {d["type"] for d in support.read_board_support(BLANK)} == {"junk"}


# ---- AC4 / AC5 ----

def pip_setup(data, monkeypatch, files, extra=None):
    touch(data, files)
    nets = {f: pip_net([2, 2]) for f in files}
    nets[support.TYPE_FILE] = type_net(["Resonance", "Alignment"])
    nets.update(extra or {})
    return fake_loader(monkeypatch, nets)


def loaded(log):
    return {n for n, _ in log}


def test_auto_uses_support_pips_when_all_three(data, monkeypatch):
    log = pip_setup(data, monkeypatch, [support.TYPE_FILE, *support.PIP_FILES, *gear.PIP_ENSEMBLE])
    out = support.read_board_support(BLANK, "auto")
    assert loaded(log) == {support.TYPE_FILE, *support.PIP_FILES}
    assert out[0]["pip"] == 2


def test_auto_falls_back_to_gear_ensemble(data, monkeypatch):
    log = pip_setup(data, monkeypatch, [support.TYPE_FILE, *support.PIP_FILES[:2], *gear.PIP_ENSEMBLE])
    support.read_board_support(BLANK, "auto")
    assert loaded(log) == {support.TYPE_FILE, *gear.PIP_ENSEMBLE}


def test_gear_source_loads_no_support_pip_or_star(data, monkeypatch):
    log = pip_setup(data, monkeypatch, [support.TYPE_FILE, *support.PIP_FILES, *support.STAR_FILES, *gear.PIP_ENSEMBLE],
                    {f: star_net([0.9, 0.9]) for f in support.STAR_FILES})
    out = support.read_board_support(BLANK, "gear")
    assert loaded(log) == {support.TYPE_FILE, *gear.PIP_ENSEMBLE}
    assert out[0]["pip"] == 2


def test_star_sets_and_demotes_pip7(data, monkeypatch):
    files = [support.TYPE_FILE, *gear.PIP_ENSEMBLE, *support.STAR_FILES]
    touch(data, files)
    nets = {f: pip_net([3, 7]) for f in gear.PIP_ENSEMBLE}
    nets[support.TYPE_FILE] = type_net(["Resonance", "Alignment"])
    nets[support.STAR_FILES[0]] = star_net([0.9, 0.3])
    nets[support.STAR_FILES[1]] = star_net([0.7, 0.3])
    nets[support.STAR_FILES[2]] = star_net([0.8, 0.3])
    fake_loader(monkeypatch, nets)
    out = support.read_board_support(BLANK, "auto")
    assert out[0]["pip"] == 7 and out[1]["pip"] == 6
    assert out[2]["pip"] == 0                                    # empty cell


def test_no_star_files_keeps_ensemble_pip(data, monkeypatch):
    touch(data, [support.TYPE_FILE, *gear.PIP_ENSEMBLE])
    nets = {f: pip_net([3, 7]) for f in gear.PIP_ENSEMBLE}
    nets[support.TYPE_FILE] = type_net(["Resonance", "Alignment"])
    fake_loader(monkeypatch, nets)
    out = support.read_board_support(BLANK, "auto")
    assert [out[0]["pip"], out[1]["pip"]] == [3, 7]


# ---- AC6 + model_files ----

def sha(b):
    return hashlib.sha256(b).hexdigest()


def write_gate(data, models, type_pass=True, pip_pass=False):
    (data / support.GATE_FILE).write_text(json.dumps({
        "created": "x", "holdout": "y", "type": {"pass": type_pass}, "pip": {"pass": pip_pass},
        "models": {n: sha((data / n).read_bytes()) for n in models}}))


def test_model_files_lists_only_existing(data):
    assert support.model_files() == []
    touch(data, [support.TYPE_FILE, support.STAR_FILES[1]])
    assert support.model_files() == [support.TYPE_FILE, support.STAR_FILES[1]]


def test_gate_missing_or_unparseable(data):
    off = {"type": False, "pip": False}
    assert support.gate_state() == off
    (data / support.GATE_FILE).write_text("{not json")
    assert support.gate_state() == off


def test_gate_pass_and_hash(data):
    touch(data, [support.TYPE_FILE, support.PIP_FILES[0]])
    write_gate(data, [support.TYPE_FILE, support.PIP_FILES[0]])
    assert support.gate_state() == {"type": True, "pip": False}
    p = data / support.PIP_FILES[0]
    p.write_bytes(p.read_bytes() + b"x")
    assert support.gate_state() == {"type": False, "pip": False}


def test_gate_flipped_byte(data):
    touch(data, [support.TYPE_FILE])
    write_gate(data, [support.TYPE_FILE], pip_pass=True)
    assert support.gate_state() == {"type": True, "pip": True}
    b = bytearray((data / support.TYPE_FILE).read_bytes()); b[0] ^= 1
    (data / support.TYPE_FILE).write_bytes(bytes(b))
    assert support.gate_state() == {"type": False, "pip": False}


def test_gate_off_for_unlisted_or_missing_model(data):
    touch(data, [support.TYPE_FILE])
    write_gate(data, [support.TYPE_FILE])
    touch(data, [support.STAR_FILES[0]])                         # retrained/new model, not gated
    assert support.gate_state() == {"type": False, "pip": False}
    (data / support.STAR_FILES[0]).unlink()
    assert support.gate_state()["type"] is True
    (data / support.TYPE_FILE).unlink()                          # listed file gone
    assert support.gate_state() == {"type": False, "pip": False}


# ---- AC7 ----

@pytest.mark.parametrize("text,want", [('force = "support"\n', "support"), ('force = ""\n', ""),
                                       ('active = "doom"\n', "")])
def test_force_deck(tmp_path, monkeypatch, text, want):
    p = tmp_path / "deck.toml"
    p.write_text(text)
    monkeypatch.setattr(support, "DECK_FILE", str(p))
    assert support.force_deck() == want


def test_force_deck_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "DECK_FILE", str(tmp_path / "none.toml"))
    assert support.force_deck() == ""


# ---- AC8 ----

def bar_frame(paste=None):
    f = noise(H, W, 1)
    if paste is not None:
        y, x = int(0.95 * H), int(0.62 * W)
        f[y:y + paste.shape[0], x:x + paste.shape[1]] = paste
    return f


def test_detect_deck_missing_template(tpl):
    assert support.detect_support_deck(bar_frame()) is False


def test_detect_deck_template(tpl):
    t = noise(30, 40, 7)
    save_rgb(tpl / "deck_support.png", t)
    assert support.detect_support_deck(bar_frame(t)) is True
    assert support.detect_support_deck(bar_frame()) is False


# ---- AC9 ----

BTN_U = (0.2, 0.5, 0.8)


def panel(cards):
    """Black panel with three green buy buttons; cards: list of (image, centre_u)."""
    f = np.zeros((H, W, 3), np.uint8)
    for u in BTN_U:
        cx = int(u * W)
        f[int(0.92 * H):int(0.955 * H), cx - 43:cx + 43] = (0, 200, 0)
    for img, u in cards:
        h, w = img.shape[:2]
        y, x = int(0.83 * H), int(u * W) - w // 2
        f[y:y + h, x:x + w] = img
    return f


@pytest.fixture
def cards(tpl):
    imgs = {"growth": noise(50, 40, 11), "a": noise(50, 40, 12), "b": noise(50, 40, 13), "res": noise(50, 40, 14)}
    for k, fn in (("growth", "ui_power_growth_card.png"), ("a", "ui_power_align_card_a.png"),
                  ("b", "ui_power_align_card_b.png"), ("res", "ui_power_res_card.png")):
        save_rgb(tpl / fn, imgs[k])
    return imgs


def centres(f):
    return gear.power_buttons(f)


def test_power_cards_found(cards):
    f = panel([(cards["growth"], 0.22), (cards["b"], 0.5), (cards["res"], 0.78)])   # Alignment: second look only
    btn = centres(f)
    assert len(btn) == 3
    got = support.power_cards(f)
    assert set(got) == {"Growth", "Alignment", "Resonance"}
    assert got["Growth"] == btn[0] and got["Alignment"] == btn[1] and got["Resonance"] == btn[2]


def test_power_cards_missing_template_or_weak_score(cards, tpl):
    (tpl / "ui_power_res_card.png").unlink()
    f = panel([(cards["growth"], 0.2), (cards["res"], 0.8)])
    got = support.power_cards(f)
    assert got["Resonance"] is None and got["Growth"] is not None and got["Alignment"] is None   # align not on screen


def test_power_cards_too_far_from_button(cards):
    f = panel([(cards["growth"], 0.35)])                          # 0.15 away from the nearest button
    assert support.power_cards(f)["Growth"] is None


def test_power_cards_one_button_higher_score_wins(cards):
    weak = np.clip(cards["res"].astype(np.int32) * 0.8 + noise(50, 40, 99) * 0.2, 0, 255).astype(np.uint8)
    f = panel([(cards["growth"], 0.17), (weak, 0.23)])
    got = support.power_cards(f)
    assert got["Growth"] == centres(f)[0] and got["Resonance"] is None


# ---- AC10 ----

def load_build_tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "build_digit_templates.py"
    spec = importlib.util.spec_from_file_location("build_digit_templates", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BTN = (0.5, 0.9)
BOX = (-0.1, -0.03, 0.1, 0.03)


def box_px():
    return (int((BTN[0] + BOX[0]) * W), int((BTN[1] + BOX[1]) * H),
            int((BTN[0] + BOX[2]) * W), int((BTN[1] + BOX[3]) * H))


def lv_crop(text):
    x0, y0, x1, y1 = box_px()
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 3, cv2.LINE_AA)
    return img


def lv_frame(crop):
    x0, y0, x1, y1 = box_px()
    f = np.zeros((H, W, 3), np.uint8)
    f[y0:y1, x0:x1] = crop[..., None]
    return f


@pytest.fixture
def lv(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    for i, n in enumerate(["61937", "40528"]):
        cv2.imwrite(str(src / f"{n}_{i}.png"), lv_crop_wide(n))
    out = tmp_path / "dtpl"
    out.mkdir()
    assert load_build_tool().build_kind("powerlv", str(src), out=str(out)) == []
    monkeypatch.setattr(digits, "_TPL", str(out))
    monkeypatch.setattr(digits, "_cache", {})
    monkeypatch.setattr(support, "LV_BOX", BOX)


def lv_crop_wide(text):
    img = np.zeros((77, 300), np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    cv2.putText(img, text, ((300 - tw) // 2, (77 + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 3, cv2.LINE_AA)
    return img


def test_level_none_without_box_or_templates(tmp_path, monkeypatch):
    assert support.LV_BOX is None
    assert support.card_level(lv_frame(lv_crop("7")), BTN) is None
    monkeypatch.setattr(support, "LV_BOX", BOX)
    monkeypatch.setattr(digits, "_TPL", str(tmp_path))
    monkeypatch.setattr(digits, "_cache", {})
    assert support.card_level(lv_frame(lv_crop("7")), BTN) is None


@pytest.mark.parametrize("n", [7, 12])
def test_level_read(lv, n):
    assert support.card_level(lv_frame(lv_crop(str(n))), BTN) == n


def test_level_half_covered_and_out_of_range(lv):
    c = lv_crop("12")
    c[:, c.shape[1] // 2:] = 255
    assert support.card_level(lv_frame(c), BTN) is None
    assert support.card_level(lv_frame(lv_crop("45")), BTN) is None


# ---- AC11 ----

def test_reload_if_changed(data):
    support.reload_if_changed()
    touch(data, [support.TYPE_FILE])
    assert support.reload_if_changed() == [support.TYPE_FILE]
    assert support.reload_if_changed() == []
    support._models["net:" + support.TYPE_FILE] = object()
    p = data / support.TYPE_FILE
    os.utime(p, (os.path.getatime(p), os.path.getmtime(p) + 10))
    assert support.reload_if_changed() == [support.TYPE_FILE]
    assert "net:" + support.TYPE_FILE not in support._models
