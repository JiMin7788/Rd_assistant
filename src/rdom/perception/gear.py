"""Gear-deck perception: board (type + pip) and the deck's UI buttons.

Deck (user 2026-10-07): Gear, Doom(파멸), Bubble, Adjust(적응), BrokenGrowth(성장).
Gears change look after 초월 (teal -> grey/red/blue at random) but are all Gear;
the colour is kept as the `variant` because the classifier sees four looks.

Everything runs on a frame normalised to NORM_H pixels tall -- the same pixel
scale as the 2026-10-07 training recording (encoded 1280 tall) -- so live grabs and
recorded frames produce the same crops. The recording's content was 39px short on
the right (sidebar inset bug, fixed by geometry.fit_chrome), which only removes the
right margin; normalised-u positions here are TRUE 9:16 content coordinates.

Models: data/gear_type.joblib, data/gear_pip.joblib (tools/train_gear.py).
"""
from __future__ import annotations
import os
import numpy as np
import cv2

from rdom.perception.board import COLS, ROWS, HALF_W, HALF_H
from rdom.perception.features import cell_features

NORM_H = 1280
CROP = 72
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_DATA = os.path.join(_ROOT, "data")
_TPL = os.path.join(_ROOT, "assets", "templates")

GEAR_VARIANTS = ("GearTeal", "GearGrey", "GearRed", "GearBlue")
TYPES = GEAR_VARIANTS + ("Bubble", "Adjust", "Growth", "Doom", "Joker")   # Joker: pink crown, from the joker boss

# UI tap targets, true content-normalised (u, v). Measured on the 2026-10-07 recording.
UI = {
    "transcend": (0.875, 0.278),        # 다이스 초월 (appears only when 9 gears connect)
    "hunt": (0.885, 0.385),             # 사냥 (golem button; same spot with/without 초월)
    "hunt_popup_ok": (0.500, 0.623),    # yellow 사냥 in the SP-golem popup
    "power_open": (0.180, 0.955),       # 주사위 강화 bar at the very bottom
    "power_gear": (0.130, 0.941),       # gear card's buy button (leftmost card)
    "power_close": (0.919, 0.784),      # X on the power-up panel
    "lobby": (0.553, 0.861),            # 로비로 가기 on the result screen
    "summon": (0.520, 0.850),           # 소환
    "support": (0.220, 0.870),          # drop point of the supporter (pip-1 + random die, 130 s cd)
    "hpsp": (0.670, 0.750),             # HP->SP event token (user: always fine to tap)
}

_models = {}


def reload_if_changed():
    """Drop cached models whose file changed on disk (hot swap between games while
    the training loop writes new weights). Returns the list of reloaded names."""
    out = []
    files = [("pipnet", "gear_pip_cnn.pt"), ("pipnet", "gear_pip_pat.pt"), ("typenet", "gear_type_cnn.pt")]
    files += [("pipnet", f) for f in PIP_ENSEMBLE] + [("doomnet", f) for f in DOOM_CENTRE]
    for key, fn in files:
        path = os.path.join(_DATA, fn)
        m = os.path.getmtime(path) if os.path.exists(path) else None
        if _models.get("mtime_" + fn) != m:
            _models.pop(key, None); _models["mtime_" + fn] = m; out.append(fn)
    return out


def _model(name):
    if name not in _models:
        import joblib
        _models[name] = joblib.load(os.path.join(_DATA, f"gear_{name}.joblib"))
    return _models[name]


def normalize(frame_rgb):
    """Resize a content frame to NORM_H tall (isotropic)."""
    h, w = frame_rgb.shape[:2]
    if h == NORM_H:
        return frame_rgb
    s = NORM_H / h
    return cv2.resize(frame_rgb, (round(w * s), NORM_H), interpolation=cv2.INTER_AREA)


def _content_w(frame):
    """True 9:16 content width in pixels -- a recorded frame may be narrower."""
    return round(frame.shape[0] * 9 / 16)


def cell_crops(frame_rgb):
    """The 15 own-board cell crops (row-major), CROP x CROP RGB."""
    f = normalize(frame_rgb)
    h, W = f.shape[0], _content_w(f)
    out = []
    for r in ROWS:
        for c in COLS:
            cx, cy, hw, hh = c * W, r * h, HALF_W * W, HALF_H * h
            crop = f[int(cy - hh):int(cy + hh), int(cx - hw):int(cx + hw)]
            out.append(cv2.resize(crop, (CROP, CROP)))
    return out


# ---- pip features (shared with tools/train_gear.py) ----

def _finehog(rgb, cells=8, bins=9):
    g = cv2.cvtColor(cv2.resize(rgb, (64, 64)), cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    ang = ((np.arctan2(gy, gx) % np.pi) / np.pi * bins).astype(int).clip(0, bins - 1)
    c = 64 // cells; out = []
    for r in range(cells):
        for q in range(cells):
            sl = (slice(r * c, (r + 1) * c), slice(q * c, (q + 1) * c))
            out.append(np.bincount(ang[sl].ravel(), mag[sl].ravel(), bins))
    v = np.concatenate(out)
    return v / (np.linalg.norm(v) + 1e-6)


def _whitemap(rgb):
    hsv = cv2.cvtColor(cv2.resize(rgb, (64, 64)), cv2.COLOR_RGB2HSV)
    w = ((hsv[..., 2] > 170) & (hsv[..., 1] < 85)).astype(np.float32)
    s = (hsv[..., 1] > 110).astype(np.float32)
    return np.concatenate([cv2.resize(w, (16, 16), interpolation=cv2.INTER_AREA).ravel(),
                           cv2.resize(s, (16, 16), interpolation=cv2.INTER_AREA).ravel()])


def pip_features(rgb, dtype):
    oh = np.array([dtype == t for t in TYPES], np.float32)
    return np.concatenate([_finehog(rgb), _whitemap(rgb), oh]).astype(np.float32)


PIP_IN = 64


def _pipnet_cls():
    import torch.nn as nn
    import torch

    class PipNet(nn.Module):
        """Crop (3x64x64) + die-type one-hot -> pip 1..7 logits."""
        def __init__(self, n_out=7):
            super().__init__()
            def blk(i, o):
                return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                                     nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                                     nn.MaxPool2d(2))
            self.f = nn.Sequential(blk(3, 24), blk(24, 48), blk(48, 64), blk(64, 96))  # -> 96x4x4
            self.emb = nn.Embedding(len(TYPES), 16)
            self.h = nn.Sequential(nn.Flatten(), nn.Dropout(0.3), nn.Linear(96 * 16 + 16, 128),
                                   nn.ReLU(), nn.Linear(128, n_out))

        def forward(self, x, t):
            z = self.f(x).flatten(1)
            return self.h[1:](torch.cat([z, self.emb(t)], 1))
    return PipNet


def __getattr__(name):            # lazy: importing gear.py must not require torch
    if name == "PipNet":
        return _pipnet_cls()
    raise AttributeError(name)


PIP_ENSEMBLE = ("gear_pip_pat_e1.pt", "gear_pip_pat_e2.pt", "gear_pip_pat_e3.pt")


def _pipnet():
    """List of pip nets. Preferred: the 3-seed dot-position ensemble (logits are
    averaged -- cut run-to-run variance on bubbles, 2026-10-09); else the single
    dot-position model; else the old class model."""
    if "pipnet" not in _models:
        import torch
        ens = [os.path.join(_DATA, f) for f in PIP_ENSEMBLE]
        pat = os.path.join(_DATA, "gear_pip_pat.pt")
        if all(os.path.exists(f) for f in ens):
            paths, mode = ens, "pattern"
        elif os.path.exists(pat):
            paths, mode = [pat], "pattern"
        else:
            paths, mode = [os.path.join(_DATA, "gear_pip_cnn.pt")], "class"
        nets = []
        for path in paths:
            net = _pipnet_cls()(); net.load_state_dict(torch.load(path)); net.eval(); nets.append(net)
        _models["pip_mode"] = mode; _models["pipnet"] = nets
    return _models["pipnet"]


TYPE_CLASSES = TYPES + ("empty", "junk", "Crystal", "Bomb")   # Crystal: obstacle HP 700; Bomb: field-effect die (2026-10-09)


def _typenet():
    if "typenet" not in _models:
        import torch
        sd = torch.load(os.path.join(_DATA, "gear_type_cnn.pt"))
        n_out = sd[[k for k in sd if k.endswith(".weight")][-1]].shape[0]   # a model trained
        net = _pipnet_cls()(n_out=n_out)                               # before a class was
        net.load_state_dict(sd)                                        # added keeps working
        _models["type_classes"] = TYPE_CLASSES[:n_out]
        net.eval(); _models["typenet"] = net
    return _models["typenet"]


def predict_types(crops):
    """(labels, confidences) from the type CNN; falls back to the RandomForest
    when data/gear_type_cnn.pt is missing."""
    if not os.path.exists(os.path.join(_DATA, "gear_type_cnn.pt")):
        P = _model("type").predict_proba(np.array([cell_features(c) for c in crops]))
        return list(_model("type").classes_[P.argmax(1)]), list(P.max(1))
    import torch
    x = np.stack([cv2.resize(c, (PIP_IN, PIP_IN)) for c in crops]).astype(np.float32) / 255.0
    x = torch.from_numpy(x.transpose(0, 3, 1, 2))
    with torch.no_grad():
        P = torch.softmax(_typenet()(x, torch.zeros(len(crops), dtype=torch.long)), 1).numpy()
    labs, conf = [_models["type_classes"][i] for i in P.argmax(1)], list(P.max(1))
    for i, c in enumerate(crops):
        if is_bomb(c):
            labs[i], conf[i] = "Bomb", 1.0
        elif labs[i] == "Bomb":                    # the CNN learned bombs from synthetic art only
            labs[i] = "junk"
    return labs, conf


def is_bomb(rgb):
    """Real bombs: a dark grey, pip-less tile with an orange spark. The type CNN
    (trained on synthetic bombs) read a live bomb as Bubble 0.35 (2026-10-10).
    On 30k labelled crops this rule fired only on bombs (4 real + 2 synthetic)."""
    h = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV); n = rgb.shape[0]; m = n // 6
    c = h[m:n - m, m:n - m]
    dark = ((c[..., 1] < 60) & (c[..., 2] > 20) & (c[..., 2] < 95)).mean()
    orange = ((c[..., 0] >= 5) & (c[..., 0] <= 25) & (c[..., 1] > 140) & (c[..., 2] > 170)).mean()
    return dark > 0.6 and 0.01 < orange < 0.3


# dot positions TL TR ML C MR BL BR -> which are lit for each pip count (die faces)
PIP_PATTERNS = np.array([
    [0, 0, 0, 1, 0, 0, 0],   # 1
    [0, 1, 0, 0, 0, 1, 0],   # 2  TR+BL
    [0, 1, 0, 1, 0, 1, 0],   # 3  TR+C+BL
    [1, 1, 0, 0, 0, 1, 1],   # 4  corners
    [1, 1, 0, 1, 0, 1, 1],   # 5  corners+C
    [1, 1, 1, 0, 1, 1, 1],   # 6  two columns of 3
    [1, 1, 1, 1, 1, 1, 1],   # 7
], np.float32)


def decode_pattern(logits, hide_centre=None):
    """Per-position dot logits (N,7) -> pip 1..7 by best pattern log-likelihood.
    hide_centre: bool mask (N,) of crops whose centre is covered (Doom's countdown
    number) -- the centre is ignored there, so 2/3, 4/5, 6/7 tie and argmax returns
    the lower one; policy.gear.DoomTracker resolves the rest by elimination."""
    lp = -np.logaddexp(0, -logits); ln = -np.logaddexp(0, logits)      # log sigmoid / log(1-sigmoid)
    if hide_centre is not None and np.any(hide_centre):
        lp = lp.copy(); ln = ln.copy()
        lp[hide_centre, 3] = 0.0; ln[hide_centre, 3] = 0.0
    ll = lp @ PIP_PATTERNS.T + ln @ (1 - PIP_PATTERNS).T                # (N,7)
    return ll.argmax(1) + 1


def predict_pips(crops, types):
    """Batch pip counts for crops whose die type is known (TYPES names)."""
    import torch
    if not crops:
        return []
    x = np.stack([cv2.resize(c, (PIP_IN, PIP_IN)) for c in crops]).astype(np.float32) / 255.0
    x = torch.from_numpy(x.transpose(0, 3, 1, 2))
    t = torch.zeros(len(crops), dtype=torch.long)   # type-blind: see train_gear_pip_cnn.py
    with torch.no_grad():
        out = np.mean([net(x, t).numpy() for net in _pipnet()], 0)
    if _models.get("pip_mode") == "pattern":
        return decode_pattern(out, np.array([t == "Doom" for t in types])).tolist()
    return (out.argmax(1) + 1).tolist()


def kind(t):
    """Collapse gear colour variants: the game logic only cares that it is a Gear."""
    return "Gear" if t in GEAR_VARIANTS else t


def hires_cell(frame_rgb, cell, size=128):
    """Native-resolution crop of one cell resized to `size` (same as the _hires
    training crops of tools/collect_gear_crops.py)."""
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb)
    r, c = ROWS[(cell - 1) // 5], COLS[(cell - 1) % 5]
    cx, cy, hw, hh = c * W, r * h, HALF_W * W, HALF_H * h
    crop = frame_rgb[int(cy - hh):int(cy + hh), int(cx - hw):int(cx + hw)]
    return cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)


DOOM_CENTRE = ("gear_doom_centre_e1.pt", "gear_doom_centre_e2.pt", "gear_doom_centre_e3.pt")


def doom_centre_prob(hires_crops):
    """P(centre pip visible) for Doom cells, from the native-res centre window.
    None when the models are missing."""
    if not hires_crops or not all(os.path.exists(os.path.join(_DATA, f)) for f in DOOM_CENTRE):
        return None
    import torch
    if "doomnet" not in _models:
        nets = []
        for f in DOOM_CENTRE:
            n = _pipnet_cls()(n_out=1); n.load_state_dict(torch.load(os.path.join(_DATA, f))); n.eval(); nets.append(n)
        _models["doomnet"] = nets
    x = np.stack([c[24:88, 32:96] for c in hires_crops]).astype(np.float32) / 255.0
    x = torch.from_numpy(x.transpose(0, 3, 1, 2)); t = torch.zeros(len(x), dtype=torch.long)
    with torch.no_grad():
        return np.mean([torch.sigmoid(n(x, t)[:, 0]).numpy() for n in _models["doomnet"]], 0)


def read_board(frame_rgb):
    """15 dicts {cell, type, variant, pip, conf}. type in Gear/Bubble/Adjust/Growth/
    Doom/empty/junk ('junk' = cell hidden by a popup/banner: unknown, not empty).
    Doom cells also get "doom_centre" (P centre pip visible): the countdown number
    sits on the centre, so the pip = corner pattern (2/4/6) + centre."""
    crops = cell_crops(frame_rgb)
    labs, conf = predict_types(crops)
    dice = [i for i, lab in enumerate(labs) if lab in TYPES]
    pips = dict(zip(dice, predict_pips([crops[i] for i in dice], [labs[i] for i in dice])))
    out = [{"cell": i + 1, "type": kind(lab), "variant": lab, "pip": pips.get(i, 0),
            "conf": float(c)} for i, (lab, c) in enumerate(zip(labs, conf))]
    dooms = [i for i in dice if labs[i] == "Doom"]
    pc = doom_centre_prob([hires_cell(frame_rgb, i + 1) for i in dooms]) if dooms else None
    if pc is not None:
        for i, p in zip(dooms, pc):
            d = out[i]; base = 1 if d["pip"] <= 1 else (d["pip"] // 2) * 2
            d["doom_centre"] = float(p)
            d["pip"] = base + 1 if (p > 0.5 and base > 1) else base
    return out


# ---- UI buttons ----

def _tpl(name):
    key = "tpl_" + name
    if key not in _models:
        im = cv2.imread(os.path.join(_TPL, f"ui_{name}.png"))
        _models[key] = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    return _models[key]


def _match(f, name, u0, v0, u1, v1):
    """Best normalised cross-correlation of template `name` inside a search box."""
    h, W = f.shape[0], _content_w(f)
    x0, y0 = int(u0 * W), int(v0 * h)
    x1, y1 = min(int(u1 * W), f.shape[1]), int(v1 * h)
    roi = f[y0:y1, x0:x1]; t = _tpl(name)
    if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
        # recorded frames lack the rightmost 39px: match the template's visible part
        t = t[:, :max(1, roi.shape[1] - 2)]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
            return 0.0
    return float(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED).max())


def transcend_tap(frame_rgb):
    """Where to tap 다이스 초월: the matched button's horizontal centre, 80% down its
    height. The fixed (0.875, 0.278) sat on the button's upper half, which overlaps
    the partner's 축복 totem -- tapping it opened the partner-info popup (user
    2026-10-09). Falls back to below the old point when the match is weak."""
    f = normalize(frame_rgb); h, W = f.shape[0], _content_w(f)
    u0, v0, u1, v1 = _UI_BOX["transcend"][0]
    x0, y0 = int(u0 * W), int(v0 * h); x1, y1 = min(int(u1 * W), f.shape[1]), int(v1 * h)
    t = _tpl("transcend"); roi = f[y0:y1, x0:x1]
    if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
        return (0.875, 0.300)
    r = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED); _, sc, _, (mx, my) = cv2.minMaxLoc(r)
    if sc < _UI_BOX["transcend"][1]:
        return (0.875, 0.300)
    return ((x0 + mx + t.shape[1] / 2) / W, (y0 + my + t.shape[0] * 0.8) / h)


# search boxes (true u,v) and accept thresholds -- see tools/verify_gear_ui.py
_UI_BOX = {
    "transcend": ((0.78, 0.20, 1.00, 0.36), 0.70),
    "hunt": ((0.78, 0.31, 1.00, 0.46), 0.70),
    "hunt_popup_btn": ((0.25, 0.57, 0.75, 0.68), 0.75),
    "power_gear_card": ((0.00, 0.79, 0.25, 0.93), 0.70),
    "hpsp_token": ((0.55, 0.66, 0.80, 0.84), 0.60),
}


def ui_scores(frame_rgb):
    f = normalize(frame_rgb)
    return {k: _match(f, k, *box) for k, (box, _) in _UI_BOX.items()}


def power_buttons(frame_rgb):
    """Centres (u,v) of the 주사위 강화 panel's green buy buttons, left -> right
    (gear first). Colour-based: the card-template matcher stopped matching once the
    cards changed look (Lv.1 + badge, 2026-10-08) and the bot left the panel open
    for minutes -- it hides 소환, so board play stalled too."""
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb)
    y0, y1 = int(0.915 * h), int(0.958 * h)
    hsv = cv2.cvtColor(frame_rgb[y0:y1, :W], cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 0] >= 45) & (hsv[..., 0] <= 80) & (hsv[..., 1] > 110) & (hsv[..., 2] > 140)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    out = [(cen[i][0] / W, (y0 + cen[i][1]) / h) for i in range(1, n)
           if st[i][2] > 0.08 * W and st[i][3] > 0.4 * (y1 - y0) and st[i][4] > 0.5 * st[i][2] * st[i][3]]
    return sorted(out)


def ui_state(frame_rgb):
    """Which deck buttons/panels are on screen: {transcend, hunt, hunt_popup, power_panel}."""
    s = ui_scores(frame_rgb)
    on = {k: s[k] >= _UI_BOX[k][1] for k in s}
    return {"transcend": on["transcend"], "hunt": on["hunt"],
            "hunt_popup": on["hunt_popup_btn"], "power_panel": len(power_buttons(frame_rgb)) >= 4,
            "hpsp": on["hpsp_token"],
            "scores": s}


# ---- field-effect banner ----
# Dark rounded banner under the score (v 0.165-0.265). Field effects announced there
# (OCR'd from the 2026-10-07 bot game) include "40초 후, 낮은 눈금 3개 파괴한 뒤 내
# 필드의 최고 눈금 주사위 1개 복제" -- the effect fires when the small countdown
# circle at the bottom right reaches 0, on BOTH fields.
BANNER_BOX = (0.15, 0.165, 0.95, 0.265)


def banner_present(frame_rgb):
    h, w = frame_rgb.shape[:2]; u0, v0, u1, v1 = BANNER_BOX
    g = cv2.cvtColor(frame_rgb[int(v0*h):int(v1*h), int(u0*w):int(u1*w)], cv2.COLOR_RGB2GRAY)
    return (g < 60).mean() >= 0.45


def banner_text(frame_rgb):
    """OCR of the field-effect banner (Korean), '' when no banner. ~0.3-1 s."""
    if not banner_present(frame_rgb):
        return ""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    h, w = frame_rgb.shape[:2]; u0, v0, u1, v1 = BANNER_BOX
    g = cv2.cvtColor(frame_rgb[int(v0*h):int(v1*h), int(u0*w):int(u1*w)], cv2.COLOR_RGB2GRAY)
    tess = os.path.abspath(os.path.join(_ROOT, "tessdata"))
    try:
        txt = pytesseract.image_to_string(g, lang="kor", config=f"--tessdata-dir {tess} --psm 6")
    except Exception:
        return ""
    return " ".join(txt.split())


def effect_kind(text):
    """Classify an OCR'd banner into the effects the bot reacts to."""
    t = text.replace(" ", "")
    # OCR mangles single syllables ("파괴" came back "파피"): require two of several cues
    if sum(k in t for k in ("낮은눈금", "3개", "파괴", "복제", "최고", "1개")) >= 3:
        return "destroy3_clone_max"
    if "보유한" in t and "획득" in t:
        return "sp_double_later"          # "60초 후, 현재 보유한 SP만큼 획득"
    if "부족할때" in t and "보너스" in t:
        return "summon_bonus_when_short"  # "소환 비용이 부족할 때 소환 버튼 클릭 시 보너스"
    return None


HP_BOX = (0.915, 0.484, 0.985, 0.508)   # digits under the tank at the right end of the mid line


def read_hp(frame_rgb):
    """Shared base HP (the number under the purple tank), int or None if unreadable.
    Needed for the HP->SP token: user 2026-10-08 -- spend HP only down to 30,
    because at HP <= 20 a field effect can appear that turns dice into random
    dice with pip +1. Exact or nothing (perception.digits); multiples of 10 only."""
    from rdom.perception.digits import read_number, hp_mask
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb); u0, v0, u1, v1 = HP_BOX
    crop = frame_rgb[int(v0 * h):int(v1 * h), int(u0 * W):int(u1 * W)]
    m = hp_mask(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    if m is None:
        return None
    r = read_number(m, "hp", thr=127)
    if r is None or len(r) > 3 or int(r) % 10:
        return None
    return int(r)


# ---- 전술효과 선택 (start-of-game tactic pick) ----
# Three dark cards; their ORDER IS RANDOM (2026-10-08: SP1000 was card 1 in one game,
# card 3 in another), so the card is chosen by reading it, never by position.
TACTIC_CARD_V = (0.365, 0.494, 0.628)


def _dark_band(frame_rgb, v):
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb)
    band = frame_rgb[int((v - 0.035) * h):int((v + 0.035) * h), int(0.30 * W):int(0.85 * W)]
    return float((cv2.cvtColor(band, cv2.COLOR_RGB2HSV)[..., 2] < 90).mean())


def tactic_sp1000_card(frame_rgb):
    """On the '원하는 전술효과를 선택하세요!' screen, (u, v) of the '즉시 SP1000 획득'
    card; None when the screen is not up or the card is not found. User rule
    2026-10-08: always pick SP1000."""
    if min(_dark_band(frame_rgb, v) for v in TACTIC_CARD_V) < 0.45:
        return None
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb)
    tess = os.path.abspath(os.path.join(_ROOT, "tessdata"))
    for v in TACTIC_CARD_V:
        crop = frame_rgb[int((v - 0.035) * h):int((v + 0.035) * h), int(0.30 * W):int(0.95 * W)]
        g = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), None, fx=1.5, fy=1.5)
        try:
            txt = pytesseract.image_to_string(g, lang="kor+eng", config=f"--tessdata-dir {tess} --psm 6")
        except Exception:
            return None
        t = txt.replace(" ", "").upper()
        if "1000" in t or "풍요" in t:
            return (0.60, v)
    # OCR missed (SP1000 is always one of the three, user 2026-10-09): fall back to the
    # card whose left icon is the most gold/orange (the coin stack)
    best = None
    for v in TACTIC_CARD_V:
        icon = frame_rgb[int((v - 0.03) * h):int((v + 0.03) * h), int(0.08 * W):int(0.28 * W)]
        hsv = cv2.cvtColor(icon, cv2.COLOR_RGB2HSV)
        gold = float(((hsv[..., 0] >= 12) & (hsv[..., 0] <= 30) & (hsv[..., 1] > 120) & (hsv[..., 2] > 150)).mean())
        if best is None or gold > best[0]:
            best = (gold, v)
    return (0.60, best[1]) if best and best[0] > 0.08 else None


ROOM_CODE_BOX = (0.36, 0.535, 0.74, 0.578)    # the digits bar in the 협동 같이하기 room


def read_room_code(frame_rgb):
    """5-digit room code shown in the coop room, as a string, or None (exact or
    nothing: perception.digits refuses ambiguous glyphs). Callers should still
    require the same code on consecutive frames before sending it anywhere."""
    from rdom.perception.digits import read_number
    h = frame_rgb.shape[0]; W = _content_w(frame_rgb); u0, v0, u1, v1 = ROOM_CODE_BOX
    g = cv2.cvtColor(frame_rgb[int(v0*h):int(v1*h), int(u0*W):int(u1*W)], cv2.COLOR_RGB2GRAY)
    return read_number(g, "room", n_digits=5)
