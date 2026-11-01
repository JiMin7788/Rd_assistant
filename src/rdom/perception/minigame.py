"""Minigame gauge (군밀 대청소 stop-the-triangle bar) recognizer.

Pure functions on an RGB content frame (no window chrome). A frame is normalised to
CANON_W = 622 px wide first (the recording's size), so half-size video frames and
full-size live frames use the same code path; every position is content-normalised
(u = x / width, v = y / height). No fixed coordinates: the bar is searched in
v 0.40-0.70.

Detection (no hue bands, docs/07): each pixel of the search strip is assigned to the
nearest of four RGB prototypes (blue, purple, yellow, dark bar) or to none when it is
farther than that prototype's tolerance. A pixel row counts as a gauge row when its
solid runs contain, with gaps <= GAP_PX, the order blue-purple-yellow-purple-blue (the
dark bar continues on either side). The gauge needs >= MIN_ROWS agreeing rows, widths
inside the fitted ranges, a red/pink triangle just under the bar (tip u = centroid of
its mask, symmetric shape) and the large green 멈춰 button at bar + 0.10 .. 0.35 in v.
Segment edges are the midpoints of the anti-aliased gaps between runs.

Reference colours (RGB, measured on the recording, fitted by fit_params):
  blue (74,155,255)  purple (171,76,252)  yellow (255,218,37)  dark bar (30,24,49)
  triangle (255,0,98)  button face (35,238,189)
Lookalikes rejected by the order + the dark bar + the triangle + the button: the
multiplier reel tiles (blue/purple/orange), the result texts above the bar (나이스 is a
cyan-blue, 완벽해 yellow, 쿨 purple).

Held-out results (tests/test_minigame_perception.py, leave-one-gauge-out, 8 folds):
  fold (held out)  labelled  within 0.005 u  worst error (tip / yellow edges)
  gauge 1             11      11 = 100 %      0.0022 u
  gauge 2             11      11 = 100 %      0.0021 u
  gauge 3             11      11 = 100 %      0.0021 u
  gauge 4              6       6 = 100 %      0.0014 u
  gauge 5             10      10 = 100 %      0.0014 u
  gauge 6             10      10 = 100 %      0.0013 u
  gauge 7             10      10 = 100 %      0.0022 u
  gauge 8             11      11 = 100 %      0.0006 u
  pooled              80      80 = 100 %      0.0022 u        gauges detected 8/8
Negatives (non-gauge screens, 33 of them mosaicked ranking lists): 180 frames, of them 95 held out
(recording time >= 90 s; the 85 before 90 s were free for tuning); 0 false gauges in both halves
with every fold's params and with DEFAULT_PARAMS. Labelled frames are spread evenly over each
gauge after the zoom-in; frames where the result text covers the bar are not labelled (the
detector returns None there, which the loop only meets after the stop).
Labels come from sub-pixel channel crossings on the original frames; the tests read WebP crops.

Proven on half-size GPG video only; full-scale GPG (1244x2224) and LD (1122x1994) are
unproven until the H5 human dry runs.
"""
from __future__ import annotations
from dataclasses import dataclass

import cv2
import numpy as np

CANON_W = 622
V_SEARCH = (0.40, 0.70)
BTN_V = (0.10, 0.35)          # button top search range below the bar
TRI_V = 0.06                  # triangle search depth under the bar (v)
GAP_PX = 5                    # anti-aliased / video-compressed gap tolerated between neighbouring runs
MIN_RUN = 2                   # shortest coloured run (px at CANON_W)
MIN_DARK = 4                  # shortest dark run
MIN_ROWS = 3                  # rows that must agree on the gauge geometry

_CLS = ("blue", "purple", "yellow", "dark")


@dataclass(frozen=True)
class GaugeRead:
    bar: tuple          # (u0, u1) dark bar span
    v: float            # bar centre row
    segments: tuple     # 5 x (name, u0, u1): blue, purple, yellow, purple, blue
    yellow: tuple       # (u0, u1)
    tip_u: object       # float | None (triangle not found)
    button: object      # (u0, v0, u1, v1) | None


@dataclass(frozen=True)
class Params:
    blue: tuple
    purple: tuple
    yellow: tuple
    dark: tuple
    tri: tuple
    green: tuple
    tol: tuple          # distance tolerance for blue, purple, yellow, dark, tri, green
    bar_w: tuple        # (min, max) bar width in u
    yellow_w: tuple     # (min, max) yellow width in u
    tri_area: float     # min triangle mask area in W^2 units
    btn_w: float        # min button width in u


# AI-NOTE: fit_params on all 8 recorded gauges (80 labelled frames), pasted as literals;
# tests/test_minigame_perception.py::test_default_params_equal_full_fit fails if they drift.
DEFAULT_PARAMS = Params(
    blue=(77.0, 154.0, 253.0), purple=(171.0, 77.0, 251.0), yellow=(250.0, 210.0, 48.0),
    dark=(32.0, 24.0, 49.0), tri=(253.0, 0.0, 97.0), green=(35.0, 239.0, 190.0),
    tol=(24.4, 39.3, 60.0, 21.7, 27.7, 60.0), bar_w=(0.5403, 0.8502),
    yellow_w=(0.0156, 0.046), tri_area=0.000889, btn_w=0.2251)


def _canon(frame):
    h, w = frame.shape[:2]
    if w == CANON_W:
        return frame
    interp = cv2.INTER_AREA if w > CANON_W else cv2.INTER_LINEAR
    return cv2.resize(frame, (CANON_W, max(1, round(h * CANON_W / w))), interpolation=interp)


def _dist(img, proto):
    d = img.astype(np.float32) - np.array(proto, np.float32)
    return np.sqrt((d * d).sum(-1))


def _classify(strip, p):
    protos = (p.blue, p.purple, p.yellow, p.dark)
    d = np.stack([_dist(strip, c) for c in protos])
    cls = d.argmin(0)
    ok = d.min(0) <= np.array(p.tol[:4], np.float32)[cls]
    return np.where(ok, cls + 1, 0).astype(np.int8)


def _runs(row):
    idx = np.flatnonzero(np.diff(row)) + 1
    starts = np.r_[0, idx]
    ends = np.r_[idx, row.size]
    return [(int(row[s]), int(s), int(e)) for s, e in zip(starts, ends)]


def _row_geometry(row):
    """Edges of blue,purple,yellow,purple,blue plus dark bar span, or None."""
    solid = [r for r in _runs(row)
             if r[0] > 0 and r[2] - r[1] >= (MIN_DARK if r[0] == 4 else MIN_RUN)]
    cl = [r[0] for r in solid]
    for i in range(len(solid) - 4):
        if cl[i:i + 5] != [1, 2, 3, 2, 1]:
            continue
        win = solid[i:i + 5]
        if any(win[k + 1][1] - win[k][2] > GAP_PX for k in range(4)):
            continue
        edges = [win[0][1]]
        edges += [(win[k][2] + win[k + 1][1]) / 2 for k in range(4)]
        edges.append(win[4][2])
        left, right = float(win[0][1]), float(win[4][2])
        if i > 0 and cl[i - 1] == 4 and win[0][1] - solid[i - 1][2] <= GAP_PX:
            left = float(solid[i - 1][1])
        if i + 5 < len(solid) and cl[i + 5] == 4 and solid[i + 5][1] - win[4][2] <= GAP_PX:
            right = float(solid[i + 5][2])
        return edges, left, right
    return None


def _largest(mask):
    n, _, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n < 2:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return float(cen[k][0]) + 0.5, int(st[k, cv2.CC_STAT_AREA]), st[k]


def _tip_px(region, p, px_per_w):
    """(centroid x in px of the region, area in W^2) of the triangle mask, or None."""
    hit = _largest(_dist(region, p.tri) <= p.tol[4])
    if hit is None:
        return None
    cx, area, _ = hit
    if area / (px_per_w ** 2) < p.tri_area:
        return None
    return cx, area / (px_per_w ** 2)


def read_bar(frame, params=DEFAULT_PARAMS):
    """Bar stage only: (canonical image, bar, v, edges, bottom row, top row) or None.

    The negative-fixture tests call this on strips that stop above the button.
    """
    p = params
    img = _canon(np.ascontiguousarray(frame))
    H, W = img.shape[:2]
    y0, y1 = int(V_SEARCH[0] * H), int(V_SEARCH[1] * H)
    cls = _classify(img[y0:y1], p)
    if (cls == 3).sum() < MIN_ROWS * MIN_RUN:
        return None
    rows = []
    for y in range(cls.shape[0]):
        g = _row_geometry(cls[y])
        if g is not None:
            rows.append((y, g))
    if len(rows) < MIN_ROWS:
        return None
    yc = np.array([(g[0][2] + g[0][3]) / 2 for _, g in rows])
    keep = [r for r, c in zip(rows, yc) if abs(c - np.median(yc)) <= 2]
    if len(keep) < MIN_ROWS:
        return None
    edges = np.median(np.array([g[0] for _, g in keep]), axis=0) / W
    # AI-NOTE: the triangle hides the dark bar next to it on some rows, which only ever shortens
    # a row's span, so the bar is the widest span any agreeing row shows.
    bar = (float(min(g[1] for _, g in keep)) / W, float(max(g[2] for _, g in keep)) / W)
    if not (p.bar_w[0] <= bar[1] - bar[0] <= p.bar_w[1]):
        return None
    if not (p.yellow_w[0] <= edges[3] - edges[2] <= p.yellow_w[1]):
        return None
    ys = [y for y, _ in keep]
    return img, bar, edges, y0 + min(ys), y0 + max(ys) + 1


def read_gauge(frame, params=DEFAULT_PARAMS):
    p = params
    found = read_bar(frame, p)
    if found is None:
        return None
    img, bar, edges, top, bot = found
    H, W = img.shape[:2]
    ty1 = min(H, bot + int(TRI_V * H))
    xa, xb = max(0, int((bar[0] - 0.03) * W)), min(W, int((bar[1] + 0.03) * W) + 1)
    tip = _tip_px(img[bot:ty1, xa:xb], p, W)
    if tip is None:
        return None
    tip_u = (xa + tip[0]) / W
    by0, by1 = bot + int(BTN_V[0] * H), min(H, bot + int(BTN_V[1] * H))
    hit = _largest(_dist(img[by0:by1], p.green) <= p.tol[5]) if by1 > by0 else None
    if hit is None or hit[2][cv2.CC_STAT_WIDTH] / W < p.btn_w:
        return None
    s = hit[2]
    button = (s[cv2.CC_STAT_LEFT] / W, (by0 + s[cv2.CC_STAT_TOP]) / H,
              (s[cv2.CC_STAT_LEFT] + s[cv2.CC_STAT_WIDTH]) / W,
              (by0 + s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT]) / H)
    names = ("blue", "purple", "yellow", "purple", "blue")
    segs = tuple((names[i], float(edges[i]), float(edges[i + 1])) for i in range(5))
    return GaugeRead(bar=bar, v=(top + bot) / 2 / H, segments=segs,
                     yellow=(float(edges[2]), float(edges[3])), tip_u=float(tip_u),
                     button=tuple(float(x) for x in button))


def read_tip(band, band_box, params=DEFAULT_PARAMS):
    """Tip u of the triangle on a crop of the content; band_box = (u0, v0, u1, v1) of the crop."""
    p = params
    u0, _, u1, _ = band_box
    hit = _tip_px(np.ascontiguousarray(band), p, band.shape[1] / (u1 - u0))
    if hit is None:
        return None
    return u0 + hit[0] / band.shape[1] * (u1 - u0)


def zone_at(read, u):
    """'yellow' | 'purple' | 'blue' | 'outside'; edges are inclusive, yellow beats purple beats blue."""
    for want in ("yellow", "purple", "blue"):
        for name, a, b in read.segments:
            if name == want and a <= u <= b:
                return want
    return "outside"


def same_gauge(a, b, tol=0.004):
    """True when two reads are the same bar layout (bar span and all segment edges within tol)."""
    if a is None or b is None:
        return False
    ea = [a.bar[0], a.bar[1]] + [s[1] for s in a.segments] + [a.segments[-1][2]]
    eb = [b.bar[0], b.bar[1]] + [s[1] for s in b.segments] + [b.segments[-1][2]]
    return all(abs(x - y) <= tol for x, y in zip(ea, eb))


def _pix(img, y, xa, xb):
    xa, xb = int(round(xa)), int(round(xb))
    return img[max(0, y - 1):y + 2, xa:xb].reshape(-1, 3) if xb > xa else img[:0, :0].reshape(-1, 3)


def fit_params(frames, labels):
    """Fit every tunable value from labelled frames. Deterministic (medians and percentiles).

    labels[i] = {bar:[u0,u1], v, seg:[b0,p0,y0,y1,p1,b1], tip, tip_v, button:[u0,v0,u1,v1]}.
    """
    pool = {k: [] for k in ("blue", "purple", "yellow", "dark", "tri", "green")}
    imgs = [_canon(np.ascontiguousarray(f)) for f in frames]
    for img, lb in zip(imgs, labels):
        H, W = img.shape[:2]
        y = int(lb["v"] * H)
        s = [e * W for e in lb["seg"]]
        bar = [e * W for e in lb["bar"]]
        sh = 2
        spans = {"blue": [(s[0], s[1]), (s[4], s[5])], "purple": [(s[1], s[2]), (s[3], s[4])],
                 "yellow": [(s[2], s[3])], "dark": [(bar[0] + 3, s[0]), (s[5], bar[1] - 3)]}
        for k, lst in spans.items():
            for a, b in lst:
                if b - a > 2 * sh + 1:
                    pool[k].append(_pix(img, y, a + sh, b - sh))
        ty = int(lb["tip_v"] * H)
        tx = lb["tip"] * W
        pool["tri"].append(_pix(img, ty, tx - 3, tx + 3))
        b = lb["button"]
        x0, y0, x1, y1 = int(b[0] * W), int(b[1] * H), int(b[2] * W), int(b[3] * H)
        pool["green"].append(img[y0:y1, x0:x1].reshape(-1, 3))
    protos = {k: tuple(float(round(v)) for v in np.median(np.concatenate(pool[k]), axis=0))
              for k in pool}
    names = list(pool)
    tol = []
    for k in names:
        d = _dist(np.concatenate(pool[k]), protos[k])
        t = max(20.0, 2.0 * float(np.percentile(d, 99)))
        if k in _CLS:
            # AI-NOTE: never reach past half the distance to another bar colour
            t = min(t, 0.5 * min(float(np.linalg.norm(np.array(protos[k]) - np.array(protos[o])))
                                 for o in _CLS if o != k))
        tol.append(float(round(min(t, 60.0), 1)))
    bw = [lb["bar"][1] - lb["bar"][0] for lb in labels]
    yw = [lb["seg"][3] - lb["seg"][2] for lb in labels]
    bwid = [lb["button"][2] - lb["button"][0] for lb in labels]
    p = Params(blue=protos["blue"], purple=protos["purple"], yellow=protos["yellow"],
               dark=protos["dark"], tri=protos["tri"], green=protos["green"], tol=tuple(tol),
               bar_w=(round(0.8 * min(bw), 4), round(1.25 * max(bw), 4)),
               yellow_w=(round(0.6 * min(yw), 4), round(1.6 * max(yw), 4)),
               tri_area=0.0, btn_w=round(0.5 * min(bwid), 4))
    areas = []
    for img, lb in zip(imgs, labels):
        H, W = img.shape[:2]
        y = int(lb["tip_v"] * H)
        reg = img[int((lb["v"]) * H) + 8:int(lb["v"] * H) + int(TRI_V * H)]
        hit = _tip_px(reg, p, W)
        if hit:
            areas.append(hit[1])
    return Params(**{**p.__dict__, "tri_area": round(0.5 * min(areas), 6) if areas else 0.0})
