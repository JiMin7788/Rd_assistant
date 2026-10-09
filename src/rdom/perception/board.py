"""Board perception (M1): read the 15 own-board cells into (type, pip).

Type is by color+edge template match against the 5 deck sprites -- validated
15/15 on a real target-deck frame. Pip counting is routed by the recognized
type, because the pip renders differently per theme (purple dot on the light
face of Light/Bubble, green dot on the green Resonance face, a neutral-dark
central dot inside Predator's number).

Coordinates are content-normalized (u,v); frames from schema-v2 sessions cover
the game content 1:1, so the same numbers apply at any capture resolution.
"""
from __future__ import annotations
import glob, os, re
import numpy as np
import cv2
from PIL import Image

# M0 grid (docs/01). Row-major, top-left = cell 1.
COLS = [0.284, 0.390, 0.499, 0.610, 0.717]
ROWS = [0.551, 0.621, 0.690]
HALF_W, HALF_H = 0.050, 0.034

# The PARTNER's field (top half of a coop screen). Same tile size and row pitch
# as ours, shifted up and very slightly wider. Fitted on four live coop frames by
# maximising confident strict_label() hits over (offset, pitch) -- the best grid
# labelled 15/15 cells. Read-only: we collect data from it (user 2026-09-28), we
# never inject input there ([[project-operating-scope]]).
OPP_COLS = [0.2715, 0.3865, 0.5015, 0.6165, 0.7315]
OPP_ROWS = [0.258, 0.328, 0.398]

DECK = ["Predator", "Light", "Resonance", "Bubble", "Switch"]
_SPRITE = {"Predator": "Dice_Predator3", "Light": "Dice_Light3",
           "Resonance": "Dice_Resonance3", "Bubble": "Dice_BUBBLE3",
           "Switch": "Dice_Switch3"}
_TPL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "assets", "templates", "dice")
N, TN = 64, 44

_RECOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                           "data", "recognizer.joblib")
_RECOGNIZER = None


def _load_recognizer():
    """Lazy-load the trained die recogniser (colour+HOG RandomForest); None if the
    model file is missing (then classify_type falls back to colour rules)."""
    global _RECOGNIZER
    if _RECOGNIZER is None:
        try:
            import joblib
            _RECOGNIZER = joblib.load(_RECOG_PATH)
        except Exception:
            _RECOGNIZER = False
    return _RECOGNIZER or None


def _hue_hist(rgb, mask=None):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sel = (s > 60) & (v > 40)
    if mask is not None:
        sel &= mask
    if sel.sum() < 20:
        return np.ones(18, np.float32) / 18
    hh = cv2.calcHist([h], [0], sel.astype(np.uint8), [18], [0, 180]).flatten()
    return (hh / hh.sum()).astype(np.float32)


def load_templates(tpl_dir=None):
    tpl_dir = tpl_dir or _TPL_DIR
    out = {}
    for name, fam in ((k, _SPRITE[k]) for k in DECK):
        rgba = Image.open(os.path.join(tpl_dir, fam + ".png")).convert("RGBA")
        a = np.array(rgba); alpha = a[:, :, 3]
        ys, xs = np.where(alpha > 40)
        cr = rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        w, h = cr.size; m = 0.15
        inner = cr.crop((int(w*m), int(h*m), int(w*(1-m)), int(h*(1-m))))
        e = cv2.Canny(np.array(inner.convert("L").resize((TN, TN))).astype(np.uint8),
                      60, 160).astype(np.float32)
        hmask = alpha[ys.min():ys.max()+1, xs.min():xs.max()+1] > 40
        out[name] = (e, _hue_hist(np.array(cr.convert("RGB")), hmask))
    return out


def _white_frac(cell_rgb):
    """Fraction of bright, low-saturation (white) pixels on the die face. Light
    is a white cloud (~0.7-0.9); Bubble is a coloured cooldown gauge (~0.2-0.5)."""
    h, w = cell_rgb.shape[:2]
    m = 0.18
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    return float(((hsv[..., 2] > 195) & (hsv[..., 1] < 60)).mean())


def _bright_frac(cell_rgb):
    """Fraction of bright (V>200) pixels on the die face. Every die has a bright
    face panel (~0.6-0.95); an empty board tile is flat tan (~0.00-0.06). Robust
    to battle overlays (range rings, effects) which add edges but no bright panel
    -- unlike edge density, which those overlays fooled into reading empty tiles
    as Predator (tan matches tan)."""
    h, w = cell_rgb.shape[:2]
    m = 0.20
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    v = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)[..., 2]
    return float((v > 200).mean())


def _dark_frac(cell_rgb):
    h, w = cell_rgb.shape[:2]
    m = 0.20
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    v = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)[..., 2]
    return float((v < 80).mean())


def _face_colors(cell_rgb):
    """Saturated-colour fractions on the die's TOP FACE, EXCLUDING the centre pip.
    The board tile overlays a coloured pip dot in the centre; measuring only the
    surrounding face (the theme symbol) removes it, so e.g. a green pip on a white
    Light no longer looks like green Resonance. Hue bands and thresholds are derived
    from the actual deck sprites (Dice_*3), measured on this same region:
      Predator tan~.28 | Resonance grn~.18 | Bubble cyan~.33 (white~.34) |
      Switch pink~.12  | Light white~.87 (everything else ~0).
    Returns (tan, green, cyan, pink, white)."""
    h, w = cell_rgb.shape[:2]
    face = cell_rgb[int(h*0.16):int(h*0.62), int(w*0.22):int(w*0.78)]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sat = S > 55
    tot = H.size

    def fr(mask):
        return float((mask & sat).sum() / tot)
    tan = fr((H >= 8) & (H <= 32))
    green = fr((H >= 40) & (H <= 90))
    cyan = fr((H >= 90) & (H <= 120))
    pink = fr((H >= 148) & (H <= 172))
    white = float(((V > 190) & (S < 55)).sum() / tot)
    return tan, green, cyan, pink, white


def _border_colors(cell_rgb):
    """Saturated-colour fractions on the die's OUTER BORDER ring. The Bubble effect
    (a near-white Dice_Glow overlay, user) whitens the die CENTRE but the die's
    frame keeps its identity colour at the border: Predator tan, Resonance green,
    Switch pink, Bubble cyan, Light purple. So under the bubble effect the border is
    where the type still shows. Returns (tan, green, cyan, pink)."""
    h, w = cell_rgb.shape[:2]
    hsv = cv2.cvtColor(cell_rgb, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    yy, xx = np.mgrid[0:h, 0:w]
    ring = ~((np.abs(yy - h / 2) < h * 0.33) & (np.abs(xx - w / 2) < w * 0.33))
    sat = (S > 60) & ring
    tot = max(int(ring.sum()), 1)

    def fr(mask):
        return float((mask & sat).sum() / tot)
    return (fr((H >= 8) & (H <= 32)), fr((H >= 40) & (H <= 95)),
            fr((H >= 95) & (H <= 120)), fr((H >= 148) & (H <= 172)))


# Abstention thresholds (docs/07 Layer A). A frame under a battle effect pushes the
# die's colour into a wrong hue band; the model then predicts a wrong class but with
# LOW probability / a small top-2 margin. We fold both into a single `conf` so the
# CellTracker can abstain (ignore the frame, keep its belief) instead of acting on a
# guess. Empty/Bomb stay rule-based with full confidence.
CONF_MIN = 0.60       # p_max below this = not sure
MARGIN_MIN = 0.25     # top1-top2 below this = ambiguous between two types
LOW_CONF = 0.45       # value returned when unsure -> below the tracker's abstain floor


def classify_type(cell_rgb, glary=False):
    """Return (type, conf). `conf` is a real confidence: high when the model is sure,
    LOW_CONF when the model's probability or top-2 margin is too small to trust (an
    effect frame). Downstream the CellTracker abstains on low conf rather than acting
    on the guess. `glary` only steers the colour fallback used when no model is loaded.
    """
    # a black "bomb" die (special-effect only) is far darker than any deck die.
    if _dark_frac(cell_rgb) > 0.55:
        return "Bomb", 1.0
    tan, green, cyan, pink, white = _face_colors(cell_rgb)
    btan, bgreen, bcyan, bpink = _border_colors(cell_rgb)
    # empty tile (flat tan panel, no die) -- caught by rule before the model, which
    # was only trained on the 5 deck dice.
    if _bright_frac(cell_rgb) < 0.12 and max(tan, green, cyan, pink, bcyan) < 0.06:
        return "empty", 1.0
    # LEARNED recogniser (RandomForest on colour+HOG shape): separates Light vs
    # Bubble, which colour alone cannot (verified). Use predict_proba so we get a
    # confidence, not a bare label. Falls back to colour rules if the model is absent.
    model = _load_recognizer()
    if model is not None:
        from rdom.perception.features import cell_features
        try:
            clf = model["model"]
            proba = clf.predict_proba(cell_features(cell_rgb).reshape(1, -1))[0]
            order = np.argsort(proba)[::-1]
            p1 = float(proba[order[0]])
            p2 = float(proba[order[1]]) if proba.size > 1 else 0.0
            lab = str(clf.classes_[order[0]])
            if p1 < CONF_MIN or (p1 - p2) < MARGIN_MIN:
                return lab, LOW_CONF          # unsure: tracker will abstain
            return lab, p1
        except Exception:
            pass
    # --- colour fallback (no model): confident matches ~0.7, unsure -> LOW_CONF ---
    # PREDATOR is robust in BOTH states: its tan wooden frame shows at the centre
    # (normal) or, when the bubble effect washes the centre white, at the BORDER.
    if tan >= 0.12 or btan >= 0.30:
        return "Predator", 0.7
    if glary:
        # Bubble effect: centre washed white, identity colour only at the border.
        if _bright_frac(cell_rgb) < 0.10:
            return "empty", 1.0
        if bgreen >= 0.30:
            return "Resonance", 0.7
        if bpink >= 0.06:
            return "Switch", 0.7
        if bcyan >= 0.22:
            return "Bubble", 0.7
        return "Light", LOW_CONF          # washed centre, no border cue -> unsure
    if _bright_frac(cell_rgb) < 0.12 and max(tan, green, cyan, pink) < 0.06:
        return "empty", 1.0
    if green >= 0.20:                     # Resonance: green face fills it (unique)
        return "Resonance", 0.7
    if pink >= 0.05:                      # Switch: pink swap arrows (unique)
        return "Switch", 0.7
    if white < 0.35:                      # Bubble: dark teal gem, little white
        return "Bubble", 0.6
    return "Light", 0.6                   # else: bright white star bloom
    # NOTE: Light vs Bubble is NOT separable to a ±10%p margin by colour -- reliable
    # Light/Bubble needs the learned recogniser (above).


def _round_blobs(mask, area, min_a=0.004, max_a=0.09, circ=0.55):
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    n = 0
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_a * area or a > max_a * area:
            continue
        p = cv2.arcLength(c, True)
        if p and 4 * np.pi * a / (p * p) >= circ:
            n += 1
    return n


def count_pips(cell_rgb, dtype):
    """Pip count, routed by the recognized die type."""
    h, w = cell_rgb.shape[:2]
    m = 0.20
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    area = face.shape[0] * face.shape[1]

    if dtype == "Predator":
        # pip is the neutral-dark dot at the die center; the "4"/"1" strokes sit
        # left and right, so restrict to a central vertical strip.
        fw = face.shape[1]
        x0, x1 = int(0.32 * fw), int(0.68 * fw)
        strip = V[:, x0:x1]
        mask = np.zeros_like(V, np.uint8)
        mask[:, x0:x1] = (strip < np.percentile(strip, 35)).astype(np.uint8)
        return max(1, _round_blobs(mask, area, min_a=0.006, circ=0.5))

    if dtype == "Resonance":
        # green pip is a darker green dot on the green face -> local contrast
        green = (H >= 42) & (H <= 95)
        if green.sum() < 20:
            return 1
        vg = V[green]
        thr = np.percentile(vg, 40)
        mask = (green & (V < thr)).astype(np.uint8)
        return max(1, _round_blobs(mask, area, circ=0.5))

    # Light / Bubble / Switch: purple/blue dot on a light face
    purple = (H >= 95) & (H <= 155)
    mask = (purple & (S > 85) & (V < np.percentile(V, 55))).astype(np.uint8)
    n = _round_blobs(mask, area)
    return max(1, n)


def is_battle(frame_rgb):
    """True if the frame shows a battle (not a menu/lobby/event screen).

    Keyed on the green Summon button, which is present in battle however many
    dice are placed -- so this works on an empty early-game board, unlike
    counting recognized dice. The band is the button's FULL width: the 달맞이
    event screen also has a green button down there, and a narrow centre patch
    saw 0.37 green on it and declared a battle, after which the bot happily
    "summoned" -- i.e. spent event currency rolling the event dice
    (2026-09-28). Measured across the full band: battle 0.75, event 0.35,
    lobby/coop-room/game-over/shop 0.00."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.83*H):int(0.88*H), int(0.34*W):int(0.66*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= 55) & (h <= 95) & (s > 90) & (v > 120)).mean()
    return green > 0.55


_TESS_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
SPEED_LABEL_REGION = (0.735, 0.800, 0.830, 0.825)   # the "1.0x/1.5x/2.0x" caption


def read_speed(frame_rgb):
    """Read the fast-forward button's caption ("2.0x") as a float, or None if it
    is not legible (loading screen, popup over it).

    Two lessons are baked in (2026-09-28). Tesseract loses the decimal POINT on
    this font -- "1.5x" comes back as "15x" -- so the pattern takes the two
    digits before the x and puts the point back itself; a strict "d.d" returned
    None, the bot concluded the caption was unreadable, and a whole battle ran at
    1.5x. And a single threshold is not enough: 150 keeps the glyphs crisp but
    eats the point, 120 keeps the point, so both are tried.
    """
    import re as _re
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _TESS_EXE
    H, W = frame_rgb.shape[:2]
    u0, v0, u1, v1 = SPEED_LABEL_REGION
    crop = frame_rgb[int(v0 * H):int(v1 * H), int(u0 * W):int(u1 * W)]
    g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    for th in (150, 120):
        _, b = cv2.threshold(g, th, 255, cv2.THRESH_BINARY)
        for psm in (8, 7):
            try:
                txt = pytesseract.image_to_string(
                    b, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.x")
            except Exception:
                return None
            m = _re.search(r"(\d)[.,]?(\d)\s*[xX]", txt)
            if m:
                return float(f"{m.group(1)}.{m.group(2)}")
    return None


def is_game_over(frame_rgb):
    """True on the '게임 종료' result screen: a big yellow banner sits at the top
    (~v0.23-0.28). Measured: game-over ~0.72 yellow there, battle ~0.0."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.23*H):int(0.28*H), int(0.15*W):int(0.85*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    yellow = ((h >= 18) & (h <= 35) & (s > 120) & (v > 150)).mean()
    return yellow > 0.3


def is_lobby(frame_rgb):
    """True on the lobby: the big green 협동 button sits at v~0.72-0.77.
    Needed because BACK on the lobby opens the "게임을 종료하시겠습니까?" dialog --
    a recovery loop must know it has already arrived and stop pressing BACK.
    Measured: lobby 0.60, coop room / battle / game-over 0.00-0.06 at this patch."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.715*H):int(0.765*H), int(0.42*W):int(0.58*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= 55) & (h <= 95) & (s > 90) & (v > 120)).mean() > 0.30
    # a shop popup (스텝업 패키지, 2026-10-10) has its green buy button right on this
    # patch: the bot took it for the lobby and tapped 친구와 하기 through the popup
    return green and not has_popup_close(frame_rgb)


def has_popup_close(frame_rgb):
    """True if a shop/event popup with the dark-red X at the bottom centre is up
    (u 0.454-0.547, v 0.910-0.962). Such popups open by themselves on the lobby
    and are closed with that X (user 2026-09-27) -- but a screen WITHOUT one (the
    coop room, a sub-menu) must be left with BACK instead, or the tap lands on
    whatever the lobby has there (다이스 트리) and opens yet another screen.
    Measured: popup 0.65, lobby 0.40 (the red die icon), coop room 0.11,
    battle/game-over 0.00."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.905*H):int(0.94*H), int(0.46*W):int(0.54*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h <= 10) | (h >= 165)) & (s > 90) & (v > 60)).mean() > 0.50


def _hsv_frac(frame_rgb, u0, v0, u1, v1, cond):
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(v0*H):int(v1*H), int(u0*W):int(u1*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV).astype(int)
    return cond(hsv[..., 0], hsv[..., 1], hsv[..., 2]).mean()


def has_modal_x(frame_rgb):
    """True if a 협동 같이하기 modal (the 친구와 하기 menu or the coop room) is up:
    its red X sits top-right (u 0.845-0.90, v 0.19-0.225). BACK does NOT close
    these modals -- only this X does. Measured 2026-10-01: menu 0.82, room 0.74,
    lobby 0.01, friend-select popup 0.00."""
    return _hsv_frac(frame_rgb, .845, .19, .90, .225,
                     lambda h, s, v: ((h <= 10) | (h >= 165)) & (s > 120) & (v > 120)) > 0.40


def is_friend_menu(frame_rgb):
    """True on the 친구와 하기 menu (yellow 방 생성 button). Measured: menu 0.87,
    lobby 0.03, room 0.00."""
    return has_modal_x(frame_rgb) and _hsv_frac(
        frame_rgb, .25, .39, .75, .44,
        lambda h, s, v: (h >= 18) & (h <= 35) & (s > 120) & (v > 150)) > 0.50


def is_coop_room(frame_rgb):
    """True in the coop room: the 협동 시작 button is there, grey while waiting or
    yellow once the friend accepted. Measured grey: room 0.88, lobby 0.21, menu
    0.13; the red X gate rules out the lobby's grey-ish art."""
    if not has_modal_x(frame_rgb):
        return False
    grey = _hsv_frac(frame_rgb, .32, .62, .68, .67, lambda h, s, v: (s < 40) & (v > 170))
    yel = _hsv_frac(frame_rgb, .32, .62, .68, .67,
                    lambda h, s, v: (h >= 18) & (h <= 35) & (s > 120) & (v > 150))
    return grey > 0.50 or yel > 0.30


def is_exit_dialog(frame_rgb):
    """True on the "게임을 종료하시겠습니까?" confirm box (BACK pressed on the lobby
    root). Detected by its yellow 확인 button -- tapping that would close the
    GAME, so the bot must recognise the box and hit 취소 instead.
    Measured: dialog 0.78 yellow there, lobby/battle/game-over 0.00."""
    H, W = frame_rgb.shape[:2]
    p = frame_rgb[int(0.605*H):int(0.635*H), int(0.62*W):int(0.78*W)]
    hsv = cv2.cvtColor(p, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return ((h >= 18) & (h <= 35) & (s > 120) & (v > 150)).mean() > 0.40


def cell_box(cu, rv, W, H):
    hw, hh = int(HALF_W * W), int(HALF_H * H)
    cx, cy = int(cu * W), int(rv * H)
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def switch_on_cooldown(cell_rgb):
    """A Switch die on cooldown shows a translucent dark wedge (the cooldown
    gauge) over part of its face, raising the dark-pixel fraction. Measured:
    ready ~0.002-0.02 vs cooling ~0.095 at V<140. Cooldown is player/pip/luck
    dependent, so reading the gauge is more reliable than a fixed timer."""
    h, w = cell_rgb.shape[:2]
    m = 0.16
    face = cell_rgb[int(h*m):int(h*(1-m)), int(w*m):int(w*(1-m))]
    v = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)[..., 2]
    return float((v < 140).mean()) > 0.05


def any_switch_ready(frame_rgb, board):
    """True if at least one Switch die on the board is off cooldown (usable)."""
    H, W = frame_rgb.shape[:2]
    for c in board:
        if c["type"] != "Switch":
            continue
        cu, rv = COLS[(c["cell"] - 1) % 5], ROWS[(c["cell"] - 1) // 5]
        x0, y0, x1, y1 = cell_box(cu, rv, W, H)
        if not switch_on_cooldown(frame_rgb[y0:y1, x0:x1]):
            return True
    return False


def _debuff_cast(frame_rgb):
    """Neutralise the opponent's YELLOW light buff ONLY when it is present. Yellow
    tints the board R,G >> B, shifting every die toward tan and collapsing
    recognition onto Predator. Detect it specifically as min(R,G) - B (measured:
    clean board ~0, yellow-buffed ~40) -- NOT overall channel spread, which a
    naturally colourful but balanced board (green resonance, teal bubble) also
    raises and which wrongly white-balanced the clean board, distorting colours and
    causing false Predator reads. A clean frame is left untouched."""
    H, W = frame_rgb.shape[:2]
    board = frame_rgb[int(0.50*H):int(0.72*H), int(0.20*W):int(0.78*W)]
    m = board.reshape(-1, 3).astype(np.float32).mean(0)
    if float(min(m[0], m[1]) - m[2]) <= 15.0:  # not a yellow cast -> leave as is
        return frame_rgb
    g = float(m.mean())
    scale = np.array([g / max(float(m[c]), 1.0) for c in range(3)], np.float32)
    return np.clip(frame_rgb.astype(np.float32) * scale, 0, 255).astype(np.uint8)


GLARE_T = 0.58        # median cell white above this = the Bubble effect is on


def _glare_of(frame_rgb):
    """Median per-cell face white-fraction on an ALREADY colour-corrected frame."""
    H, W = frame_rgb.shape[:2]
    ws = []
    for rv in ROWS:
        for cu in COLS:
            x0, y0, x1, y1 = cell_box(cu, rv, W, H)
            face = frame_rgb[y0:y1, x0:x1]
            h, w = face.shape[:2]
            face = face[int(h*0.16):int(h*0.62), int(w*0.22):int(w*0.78)]
            hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
            ws.append(float(((hsv[..., 2] > 190) & (hsv[..., 1] < 55)).mean()))
    return float(np.median(ws))


def board_glare(frame_rgb):
    """Median per-cell face white-fraction -- the Bubble effect (user) is a near-white
    overlay that washes every die centre toward white; the pale Predator/Resonance/
    Light then look alike from the centre. The median cell reads very white (measured:
    normal board ~0.48, bubble-effect ~0.84). Above GLARE_T the reader switches to the
    die BORDER colour (which keeps its identity) instead of the washed centre."""
    return _glare_of(_debuff_cast(frame_rgb))


def read_board_stable(grab, tpls=None, n=5, dt=0.22):
    """Majority-vote the type of each cell across n grabs to filter transient
    misreads (battle glow, animations) that make a cell flicker between types and
    thrash placement. Own-field dice do not move without our input, so within a
    fraction of a second every grab should agree -- disagreement is noise, and the
    mode wins. Returns the same shape as read_board (pip fixed at 1)."""
    import time as _t
    from collections import Counter
    tpls = tpls or load_templates()
    votes = [Counter() for _ in range(15)]
    got = 0
    for k in range(n):
        try:                                    # dxcam yields no frame if grabbed
            frame = grab.grab()                 # faster than the display refreshes
        except RuntimeError:
            _t.sleep(dt); continue
        b = read_board(frame, tpls)
        for i, c in enumerate(b):
            votes[i][c["type"]] += 1
        got += 1
        if k < n - 1:
            _t.sleep(dt)
    if got == 0:                                # never a frame -> one blocking grab
        b = read_board(grab.grab(), tpls)
        for i, c in enumerate(b):
            votes[i][c["type"]] += 1
    out = []
    for i in range(15):
        t = votes[i].most_common(1)[0][0]
        out.append({"cell": i + 1, "type": t, "pip": 0 if t == "empty" else 1,
                    "score": 1.0})
    return out


def read_board(frame_rgb, tpls=None):
    """Return list of 15 dicts: {cell, type, pip, score}, row-major."""
    frame_rgb = _debuff_cast(frame_rgb)        # undo buff colour casts (yellow)
    glary = _glare_of(frame_rgb) > GLARE_T      # Bubble effect on -> read borders
    H, W = frame_rgb.shape[:2]
    out = []
    i = 0
    for rv in ROWS:
        for cu in COLS:
            x0, y0, x1, y1 = cell_box(cu, rv, W, H)
            crop = frame_rgb[y0:y1, x0:x1]
            dtype, conf = classify_type(crop, glary)
            # pip>=2 detection (user 2026-09-17: skill removes pip2+ to keep the board
            # pip-1 pure). Only for the types where dot-counting is reliable AND only on
            # a CONFIDENT type read (an effect frame abstains). Switch is excluded -- its
            # swap-arrow icon is miscounted as extra pips (validated 14/15, switch the
            # lone error). The tracker still requires several pip2 frames before acting.
            pip2 = (dtype in ("Predator", "Light", "Bubble", "Resonance")
                    and conf >= CONF_MIN and count_pips(crop, dtype) >= 2)
            # This is a pip-1 deck by design (user): every die is summoned at pip 1
            # and the bot never merges into a target cell, so the whole board stays
            # pip 1. count_pips() is unreliable on the pale live faces (reads pip
            # 2/3 for pip-1 dice), and a wrong pip silently blocks switch swaps
            # (same-pip only) and completion (predator pips must align). Assuming
            # pip 1 is both more accurate here and removes that dependency.
            pip = 0 if dtype == "empty" else 1
            out.append({"cell": i + 1, "type": dtype, "pip": pip, "pip2": bool(pip2),
                        "score": round(conf, 3), "conf": round(conf, 3)})
            i += 1
    return out
