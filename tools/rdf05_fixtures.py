"""Cut the rdF05 gauge fixtures, labels and traces from the GPG recording (read-only).

  python tools/rdf05_fixtures.py cut      # frames/, neg/, full/, labels.json, README.md, .scratch montage
  python tools/rdf05_fixtures.py traces   # traces.json with read_gauge (DEFAULT_PARAMS) on every gauge frame

The recording is read by absolute path and never copied. Frames are stored as crops of the
content (positives v 0.40-0.86, negatives v 0.40-0.70 of the 622x1116 canon); the tests pad them back with black.
Labels come from sub-pixel channel crossings (not from the detector's class runs); the
detector with hand-set seed params only supplies the rough position to refine.
Ranking-list frames (nicknames, own account name) are mosaicked before saving (Hard Rule R5).
"""
from __future__ import annotations
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.perception import minigame as mg  # noqa: E402

VIDEO = "C:/dev/_hub/features/minigame/rec/gpg_20261102_003916.mp4"
FPS = 60.0
OUT = os.path.join(ROOT, "tests", "fixtures", "rdf05")
SCRATCH = os.path.join(ROOT, ".scratch")
CROP_V = (0.40, 0.86)      # positives; negatives keep only the bar search strip below
NEG_V = (0.40, 0.70)
# gauge frame ranges found by scanning the recording (settled yellow edges jump between gauges)
GAUGES = [(3380, 3658), (3659, 3783), (4523, 4939), (4940, 5086),
          (5754, 5968), (5969, 6193), (7000, 7206), (7207, 7421)]
LABELS_PER_GAUGE = 11
N_NEG_EARLY, N_NEG_LATE = 85, 95          # < 90 s tuning half / >= 90 s held-out half
SEED = mg.Params(blue=(74, 155, 255), purple=(171, 76, 252), yellow=(255, 218, 37),
                 dark=(30, 24, 49), tri=(255, 0, 98), green=(35, 238, 189),
                 tol=(35, 35, 35, 22, 40, 30), bar_w=(.4, .9), yellow_w=(.01, .09),
                 tri_area=0.0002, btn_w=.15)


def frames_at(idx):
    cap = cv2.VideoCapture(VIDEO)
    out = {}
    for n in sorted(idx):
        cap.set(cv2.CAP_PROP_POS_FRAMES, n)
        ok, f = cap.read()
        assert ok, n
        out[n] = np.ascontiguousarray(f[:, :, ::-1])
    return out


def crop(img, v=CROP_V):
    H = img.shape[0]
    return img[int(v[0] * H):int(v[1] * H)]


def save_img(path, rgb, q):
    """WebP (about half the JPEG size on this noisy video); the 3 MB fixture budget needs it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    assert cv2.imwrite(path, rgb[:, :, ::-1], [cv2.IMWRITE_WEBP_QUALITY, q])


def crossing(row, a, b, ch, thr):
    """Sub-pixel x in [a, b] where channel ch of row crosses thr (linear interpolation)."""
    a, b = int(round(a)), int(round(b))
    v = row[a:b + 1, ch].astype(float) - thr
    for i in range(len(v) - 1):
        if v[i] == 0:
            return a + i + 0.5
        if v[i] * v[i + 1] < 0:
            return a + i + 0.5 + v[i] / (v[i] - v[i + 1])
    return None


def label_frame(img, seed):
    """Independent sub-pixel labels around the seed read; None if any crossing is missing."""
    H, W = img.shape[:2]
    y = int(seed.v * H)
    e = [seg[1] * W for seg in seed.segments] + [seed.segments[-1][2] * W]
    rows = [img[y + d] for d in (-2, 0, 2)]
    plan = [(e[0], 1, 90), (e[1], 0, 122), (e[2], 2, 145), (e[3], 2, 145), (e[4], 0, 122), (e[5], 1, 90)]
    seg = []
    for x, ch, thr in plan:
        xs = [crossing(r, x - 5, x + 5, ch, thr) for r in rows]
        if any(v is None for v in xs):
            return None
        seg.append(float(np.mean(xs)) / W)
    bar = []
    for x, sgn in ((seed.bar[0] * W, 1), (seed.bar[1] * W, -1)):
        xs = []
        for r in rows:
            lum = r.astype(int).sum(-1)
            lo, hi = int(x) - 6, int(x) + 6
            xs.append(crossing(np.stack([lum] * 3, -1), lo, hi, 0, 150))
        if any(v is None for v in xs):
            return None
        bar.append(float(np.mean(xs)) / W)
    # triangle: midpoint of the red-and-not-green crossings on rows below the bar (the bar's
    # purple has a red channel above 150 too, so rows inside the bar would mislead)
    mids = []
    tx = seed.tip_u * W
    for dy in range(15, 25):
        r = img[y + dy].astype(float)
        f = np.minimum(r[:, 0] - 150, 40 - r[:, 1])
        fr = np.stack([f, f, f], -1)
        l = crossing(fr, tx - 25, tx, 0, 0)
        rr = crossing(fr, tx, tx + 25, 0, 0)
        if l is None or rr is None:
            continue
        mids.append((l + rr) / 2)
    if len(mids) < 4:
        return None
    return {"bar": bar, "v": seed.v, "seg": seg, "tip": float(np.mean(mids)) / W,
            "tip_v": (y + 18) / H, "button": list(seed.button)}


def is_event_screen(img):
    reg = img[int(.45 * img.shape[0]):int(.80 * img.shape[0])]
    hsv = cv2.cvtColor(reg[:, :, ::-1], cv2.COLOR_BGR2HSV)
    return reg.mean() > 105 and (hsv[..., 1] > 120).mean() > 0.7


def mosaic(img):
    h, w = img.shape[:2]
    return cv2.resize(cv2.resize(img, (w // 12, h // 12), interpolation=cv2.INTER_AREA), (w, h),
                      interpolation=cv2.INTER_NEAREST)


def cut():
    os.makedirs(SCRATCH, exist_ok=True)
    # labelled frames: evenly spaced over each settled gauge (skip the zoom-in start)
    pick = []
    for g, (a, b) in enumerate(GAUGES):
        for n in np.linspace(a + 12, b, LABELS_PER_GAUGE).astype(int):
            pick.append((g, int(n)))
    full_idx = [int((a + b) // 2) for a, b in GAUGES]
    zoom_idx = [GAUGES[0][0], GAUGES[0][0] + 1, GAUGES[0][0] + 2, GAUGES[0][0] + 3]
    gauge_zone = np.zeros(8866, bool)
    for a, b in GAUGES:
        gauge_zone[max(0, a - 30):b + 90] = True   # result text lingers ~1 s after the last bar read
    elig = np.flatnonzero(~gauge_zone)
    early = elig[elig / FPS < 90]
    late = elig[elig / FPS >= 90]
    neg = list(early[np.linspace(0, len(early) - 1, N_NEG_EARLY).astype(int)]) + \
        list(late[np.linspace(0, len(late) - 1, N_NEG_LATE).astype(int)])
    want = {n for _, n in pick} | set(full_idx) | set(zoom_idx) | {int(n) for n in neg}
    imgs = frames_at(want)
    labels, sheet = [], []
    for old in ("frames", "neg", "full", "zoom"):
        d = os.path.join(OUT, old)
        if os.path.isdir(d):
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
    for g, n in pick:
        seed = mg.read_gauge(imgs[n], SEED)
        lb = label_frame(imgs[n], seed) if seed else None
        if lb is None:
            print("skip unlabelled", g, n)
            continue
        name = "frames/g%d_%05d.webp" % (g + 1, n)
        save_img(os.path.join(OUT, name), crop(imgs[n]), 60)
        lb.update(file=name, gauge=g + 1, frame=n, t=round(n / FPS, 3))
        labels.append(lb)
        H, W = imgs[n].shape[:2]
        y = int(lb["v"] * H)
        band = imgs[n][y - 30:y + 60].copy()
        band = cv2.resize(band, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        for u in lb["seg"][2:4]:
            cv2.line(band, (int(u * W * 4), 0), (int(u * W * 4), 360), (255, 255, 255), 1)
        for u in lb["bar"]:
            cv2.line(band, (int(u * W * 4), 100), (int(u * W * 4), 160), (0, 255, 0), 1)
        cv2.line(band, (int(lb["tip"] * W * 4), 120), (int(lb["tip"] * W * 4), 260), (0, 255, 255), 1)
        sheet.append(cv2.resize(band, None, fx=0.5, fy=0.5)[:, 400:1900])
    json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
    for i in range(0, len(sheet), 4):
        chunk = sheet[i:i + 4]
        cv2.imwrite(os.path.join(SCRATCH, "montage_%02d.png" % (i // 4)),
                    np.vstack(chunk)[:, :, ::-1])
    for n in full_idx:
        save_img(os.path.join(OUT, "full", "f_%05d.webp" % n), imgs[n], 50)
    for n in zoom_idx:
        save_img(os.path.join(OUT, "zoom", "z_%05d.webp" % n), crop(imgs[n]), 60)
    negs = []
    for n in sorted(neg):
        n = int(n)
        im = imgs[n]
        t = n / FPS
        c = crop(im, NEG_V)
        rank = 5.5 <= t < 38.0 and not is_event_screen(im)
        if rank:
            c = mosaic(c)
        save_img(os.path.join(OUT, "neg", "n_%05d.webp" % n), c, 45)
        negs.append((n, rank))
    thumbs = [cv2.resize(cv2.imread(os.path.join(OUT, "neg", "n_%05d.webp" % n)), (124, 67))
              for n, _ in negs]
    thumbs += [np.zeros_like(thumbs[0])] * (-len(thumbs) % 10)
    cv2.imwrite(os.path.join(SCRATCH, "neg_montage.png"),
                np.vstack([np.hstack(thumbs[i:i + 10]) for i in range(0, len(thumbs), 10)]))
    json.dump({"neg": [{"file": "neg/n_%05d.webp" % n, "frame": n, "t": round(n / FPS, 3),
                        "mosaic": r} for n, r in negs]},
              open(os.path.join(OUT, "negatives.json"), "w"), indent=1)
    print("labelled", len(labels), "neg", len(negs), "ranking mosaicked", sum(r for _, r in negs))


def traces():
    cap = cv2.VideoCapture(VIDEO)
    out = {}
    for g, (a, b) in enumerate(GAUGES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, a)
        series, yellow = [], []
        for n in range(a, b + 1):
            ok, f = cap.read()
            r = mg.read_gauge(np.ascontiguousarray(f[:, :, ::-1]))
            if r is not None and r.tip_u is not None:
                series.append([round(n / FPS, 4), round(r.tip_u, 5)])
                if n - a >= 12:
                    yellow.append(r.yellow)
        tips = np.array([s[1] for s in series])
        moved = np.flatnonzero(np.abs(tips - tips[-1]) > 0.002)
        stop = int(round(series[min(moved[-1] + 1, len(series) - 1)][0] * FPS)) if len(moved) else a
        out[str(g + 1)] = {"frames": [a, b], "series": series,
                           "yellow": [round(float(np.median([y[0] for y in yellow])), 5),
                                      round(float(np.median([y[1] for y in yellow])), 5)],
                           "stop_frame": stop, "stop_t": round(stop / FPS, 4)}
    json.dump({"fps": FPS, "gauges": out}, open(os.path.join(OUT, "traces.json"), "w"))
    print({k: (v["stop_frame"], len(v["series"])) for k, v in out.items()})


if __name__ == "__main__":
    {"cut": cut, "traces": traces}[sys.argv[1]]()
