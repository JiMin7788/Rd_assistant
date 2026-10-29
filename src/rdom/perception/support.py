"""Support-deck perception: board (type + pip), R4 gate state, deck bar, power cards, card level.

The support deck has its own models (data/support_*.pt) because PipNet embeds
len(gear.TYPES) types: growing gear.TYPES would break loading the gear pip weights.
Nothing here touches a gear model or gear.TYPES. torch is imported lazily.

Pip sources (read_board_support): "auto" uses the support pip ensemble when all three
files exist, else the gear ensemble; "gear" (trial mode) always uses the gear
ensemble and loads no support pip or star file.
"""
from __future__ import annotations
import hashlib
import json
import numbers
import os
import tomllib
import numpy as np
import cv2

from rdom.perception import digits, gear

SUPPORT_CLASSES = ("Resonance", "Alignment", "Bubble", "Adjust", "Growth", "Joker",
                   "empty", "junk", "Crystal", "Bomb")
NO_PIP = ("empty", "junk", "Crystal", "Bomb")

TYPE_FILE = "support_type_cnn.pt"
PIP_FILES = tuple(f"support_pip_pat_e{i}.pt" for i in (1, 2, 3))
STAR_FILES = tuple(f"support_star_e{i}.pt" for i in (1, 2, 3))
STAR_THRESHOLD = 0.7     # star = pip 7 when p > this; measured on the H2 holdout 2026-10-30 (0.5: precision 0.838, 0.7: 0.954)
GATE_FILE = "support_gate.json"
GEAR_PIP_SINGLE = "gear_pip_pat.pt"

_DATA = gear._DATA
_TPL = gear._TPL
DECK_FILE = gear.DECK_FILE

DECK_BAR_BOX = (0.55, 0.93, 0.92, 0.99)
DECK_BAR_MIN = 0.70
POWER_BAND = (0.0, 0.78, 1.0, 0.96)
POWER_MIN = 0.70
POWER_DU = 0.06
# Card templates: the dice icon only (lower part, below the dice-count badge, above 'Lv.N'),
# cut from the normalised power-panel frame data/support_frames/sup20261029_135038/panel_121.1.png.
# Identity comes from matching the card icon with board dice of the same look in that frame, whose
# labels are support_type_cnn's, not from slot order:
#   Resonance (card 1, u 0.13): white octagon with a green centre dot = board cells 1, 5, 10, 14, 15
#     of the same frame (CNN: Resonance).
#   Alignment (card 2, u 0.31): yellow-framed cross-arrow die; the board look of cells 4 and 13 (CNN:
#     Alignment) has the same arrows. Only this look is on the panel, so there is no _b template.
#   Growth (card 5, u 0.86): white up/down-arrow die with a purple pip = the Growth die of
#     sup20261029_141449/335.8.png cell 10 and sup20261029_152652/30.3.png cell 7 (CNN: Growth,
#     conf 0.93-0.95); no other card of the panel has that face.
CARD_TEMPLATES = {
    "Growth": ("ui_power_growth_card.png",),
    "Alignment": ("ui_power_align_card_a.png", "ui_power_align_card_b.png"),   # _b: only if a second look is found
    "Resonance": ("ui_power_res_card.png",),
}
# (du0, dv0, du1, dv1) offsets from the buy-button centre, content-normalised (u over the content
# width, v over the height). Measured on the five H1 panels sup20261029_{135038,141449,143137,145953,152652}/
# panel_*.png (Lv.1 and Lv.2): the digits of Resonance/Alignment/Growth sit at +17..+46 px, -88..-62 px
# of a 1251x2224 frame. The 'Lv.' dot ends at +20 px for the Growth card, so the box starts there
# (a dot inside the box makes digits.glyphs return None) and ends at +56 px for a second digit.
LV_BOX = (0.0160, -0.0414, 0.0448, -0.0261)
LV_RANGE = (1, 30)

# A read is unreadable when its type is junk or conf < READ_CONF_MIN. Measured with
# tools/support_conf_report.py --holdout sup20261029_152652 --tags sup1 --data-dir C:/dev/rdom/data:
#   conf >= 0.90: kept 1003/1008 (99.5%), accuracy of kept 0.997, wrong kept 3, wrong dropped 1
#   chosen READ_CONF_MIN = 0.90 (largest with kept >= 95%)
READ_CONF_MIN = 0.90

_models = {}


# ---- models ----

def _load_net(path, n_out):
    """PipNet (gear's class) with weights from `path`, in eval mode."""
    import torch
    net = gear._pipnet_cls()(n_out=n_out)
    net.load_state_dict(torch.load(path))
    net.eval()
    return net


def _net(fname, n_out):
    key = "net:" + fname
    if key not in _models:
        _models[key] = _load_net(os.path.join(_DATA, fname), n_out)
    return _models[key]


def _exists(fname):
    return os.path.exists(os.path.join(_DATA, fname))


def _batch(crops):
    """List of RGB crops -> float tensor (N,3,PIP_IN,PIP_IN) and a zero type vector."""
    import torch
    x = np.stack([cv2.resize(c, (gear.PIP_IN, gear.PIP_IN)) for c in crops]).astype(np.float32) / 255.0
    return torch.from_numpy(x.transpose(0, 3, 1, 2)), torch.zeros(len(crops), dtype=torch.long)


def _logits(net, crops):
    import torch
    x, t = _batch(crops)
    with torch.no_grad():
        out = net(x, t)
    return out.numpy() if hasattr(out, "numpy") else np.asarray(out)


def predict_types_support(crops):
    """(labels, confidences). Without support_type_cnn.pt every cell is 'junk' (unknown)."""
    if not crops or not _exists(TYPE_FILE):
        return ["junk"] * len(crops), [0.0] * len(crops)
    z = _logits(_net(TYPE_FILE, len(SUPPORT_CLASSES)), crops)
    P = np.exp(z - z.max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
    labs = [SUPPORT_CLASSES[i] for i in P.argmax(1)]
    conf = [float(c) for c in P.max(1)]
    for i, c in enumerate(crops):
        if gear.is_bomb(c):
            labs[i], conf[i] = "Bomb", 1.0
        elif labs[i] == "Bomb":                    # AI-NOTE: as in gear.predict_types, the CNN's bombs come from synthetic art only
            labs[i] = "junk"
    return labs, conf


def _pip_files(pip_source):
    """File names of the pip nets to use, or [] when none exist."""
    if pip_source != "gear" and all(_exists(f) for f in PIP_FILES):
        return list(PIP_FILES)
    if all(_exists(f) for f in gear.PIP_ENSEMBLE):
        return list(gear.PIP_ENSEMBLE)
    if _exists(GEAR_PIP_SINGLE):
        return [GEAR_PIP_SINGLE]
    return []


def predict_pips_support(crops, pip_source="auto"):
    """Pip 1..7 per crop (dot-pattern decode of the averaged logits); 0 when no pip net exists."""
    if not crops:
        return []
    files = _pip_files(pip_source)
    if not files:
        return [0] * len(crops)
    out = np.mean([_logits(_net(f, 7), crops) for f in files], 0)
    return [int(p) for p in gear.decode_pattern(out)]


def star_prob(hires_crops):
    """Mean P(star in the centre) per hires crop; None unless all three star nets exist."""
    if not hires_crops or not all(_exists(f) for f in STAR_FILES):
        return None
    outs = [1 /(1 + np.exp(-_logits(_net(f, 1), hires_crops)[:, 0])) for f in STAR_FILES]
    return np.mean(outs, 0)


def read_cells_support(frame_rgb, cells, pip_source="auto"):
    """Raw reads {cell, type, variant, pip, conf} of the given cells (1..15), in the given order.
    Pip 7 is the star detector's call when the star nets exist (auto only): p > STAR_THRESHOLD -> 7, else a 7 becomes 6.
    A cell outside 1..15, a bool or a non-integer raises ValueError (nothing is read)."""
    cells = list(cells)
    # AI-NOTE: without this check cell 0 / negatives index the crop list from the end (another cell's read under the wrong label);
    # True would read cell 1 and 2.5 died with a TypeError, so bools and non-integers get the same ValueError
    bad = [c for c in cells
           if isinstance(c, bool) or not isinstance(c, numbers.Integral) or not 1 <= c <= 15]
    if bad:
        raise ValueError(f"cells must be in 1..15, got {bad}")
    all_crops = gear.cell_crops(frame_rgb)
    crops = [all_crops[c - 1] for c in cells]
    labs, conf = predict_types_support(crops)
    dice = [i for i, lab in enumerate(labs) if lab not in NO_PIP]
    pips = dict(zip(dice, predict_pips_support([crops[i] for i in dice], pip_source)))
    if dice and pip_source != "gear":
        sp = star_prob([gear.hires_cell(frame_rgb, cells[i], 128) for i in dice])
        if sp is not None:
            for i, p in zip(dice, sp):
                pips[i] = 7 if p > STAR_THRESHOLD else min(pips[i], 6)
    return [{"cell": c, "type": lab, "variant": lab, "pip": pips.get(i, 0), "conf": float(cf)}
            for i, (c, lab, cf) in enumerate(zip(cells, labs, conf))]


def read_board_support(frame_rgb, pip_source="auto"):
    """15 dicts {cell, type, variant, pip, conf}, cell order 1..15."""
    return read_cells_support(frame_rgb, range(1, 16), pip_source)


# ---- gate (Hard Rule R4) ----

def model_files():
    """Support model files that exist in the data dir (type, pip, star)."""
    return [f for f in (TYPE_FILE,) + PIP_FILES + STAR_FILES if _exists(f)]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gate_state():
    """{"type": bool, "pip": bool}: the recognizer passed its gate AND the files on disk are
    the gated ones. AI-NOTE: any listed file that is missing or changed, or any present
    support model that is not listed (a retrained model), turns both off until re-gated."""
    off = {"type": False, "pip": False}
    try:
        with open(os.path.join(_DATA, GATE_FILE), encoding="utf-8") as f:
            g = json.load(f)
        listed = g["models"]
        if not isinstance(listed, dict) or any(f not in listed for f in model_files()):
            return off
        for fn, sha in listed.items():
            p = os.path.join(_DATA, fn)
            if not os.path.exists(p) or _sha256(p) != sha:
                return off
        return {"type": g["type"]["pass"] is True, "pip": g["pip"]["pass"] is True}
    except (OSError, ValueError, KeyError, TypeError):
        return off


def force_deck():
    """`force` from config/deck.toml ('' = detect from the deck bar)."""
    try:
        with open(DECK_FILE, "rb") as f:
            v = tomllib.load(f).get("force", "")
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return v if isinstance(v, str) else ""


# ---- templates / UI ----

def _tpl(fname):
    """RGB template from the templates dir, cached by mtime; None when the file is missing."""
    p = os.path.join(_TPL, fname)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    key = "tpl:" + p
    if _models.get(key, (None,))[0] != mt:
        im = cv2.imread(p)
        _models[key] = (mt, None if im is None else cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
    return _models[key][1]


def _search(f, box, t):
    """(score, centre_u, centre_v) of the best multi-scale match of t in box of normalised frame f."""
    h, W = f.shape[0], gear._content_w(f)
    u0, v0, u1, v1 = box
    x0, y0 = int(u0 * W), int(v0 * h)
    roi = f[y0:int(v1 * h), x0:min(int(u1 * W), f.shape[1])]
    sc, (mx, my), (tw, th) = gear._best(roi, t)
    return sc, (x0 + mx + tw / 2) / W, (y0 + my + th / 2) / h


def detect_support_deck(frame_rgb):
    """True when the support deck's emblem is in the deck bar."""
    t = _tpl("deck_support.png")
    if t is None:
        return False
    return _search(gear.normalize(frame_rgb), DECK_BAR_BOX, t)[0] >= DECK_BAR_MIN


def power_cards(frame_rgb):
    """{"Growth"|"Alignment"|"Resonance": (u, v) of the card's buy button, or None}. The
    button is the one nearest in u to the matched card (|du| < POWER_DU): the support
    deck's slot order is the user's choice, so deck order cannot be used."""
    f = gear.normalize(frame_rgb)
    buttons = gear.power_buttons(f)
    hits = {}
    for name, files in CARD_TEMPLATES.items():
        best = None
        for fn in files:
            t = _tpl(fn)
            if t is None:
                continue
            sc, u, _ = _search(f, POWER_BAND, t)
            if best is None or sc > best[0]:
                best = (sc, u)
        if best is None or best[0] < POWER_MIN or not buttons:
            continue
        b = min(buttons, key=lambda b: abs(b[0] - best[1]))
        if abs(b[0] - best[1]) < POWER_DU:
            hits[name] = (best[0], b)
    out = {name: None for name in CARD_TEMPLATES}
    for name, (sc, b) in sorted(hits.items(), key=lambda kv: -kv[1][0]):
        if all(b != o for o in out.values() if o is not None):   # two cards on one button: higher score wins
            out[name] = b
    return out


def card_level(frame_rgb, button):
    """Level (1..30) printed on the card whose buy button is at `button` (u, v); exact or None."""
    if LV_BOX is None:
        return None
    h = frame_rgb.shape[0]; W = gear._content_w(frame_rgb)
    du0, dv0, du1, dv1 = LV_BOX
    x0, x1 = int((button[0] + du0) * W), int((button[0] + du1) * W)
    y0, y1 = int((button[1] + dv0) * h), int((button[1] + dv1) * h)
    crop = frame_rgb[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
    if crop.size == 0:
        return None
    try:
        r = digits.read_number(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), "powerlv")
    except OSError:                                      # no digits_powerlv.npz yet
        return None
    if r is None or not LV_RANGE[0] <= int(r) <= LV_RANGE[1]:
        return None
    return int(r)


def reload_if_changed():
    """Drop cached models whose file changed on disk (hot swap between games).
    Returns the names whose mtime changed."""
    out = []
    for fn in (TYPE_FILE,) + PIP_FILES + STAR_FILES + tuple(gear.PIP_ENSEMBLE) + (GEAR_PIP_SINGLE,):
        path = os.path.join(_DATA, fn)
        m = os.path.getmtime(path) if os.path.exists(path) else None
        if _models.get("mtime:" + fn) != m:
            _models.pop("net:" + fn, None); _models["mtime:" + fn] = m; out.append(fn)
    return out
