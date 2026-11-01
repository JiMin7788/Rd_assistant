"""Gauge recognizer gate (rdF05-t1): leave-one-gauge-out on labelled frames cut from the GPG recording.

Adjacent frames of one gauge are near-identical, so the split is by gauge (8 folds), never by frame.
Fixtures: tests/fixtures/rdf05 (README.md names the source time of every file).
"""
import json
import os
from functools import lru_cache

import cv2
import numpy as np
import pytest

from rdom.perception import minigame as mg

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "rdf05")
TOL = 0.005
H, W = 1116, 622
Y0 = int(0.40 * H)       # every stored crop starts at v 0.40 of the 622x1116 content frame


@lru_cache(maxsize=None)
def load(rel):
    """Stored crop -> RGB content frame, padded with black above/below (tools/rdf05_fixtures.py)."""
    img = cv2.imread(os.path.join(FIX, rel))[:, :, ::-1]
    if img.shape[0] == H:
        return img
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[Y0:Y0 + img.shape[0]] = img
    return canvas


@pytest.fixture(scope="module")
def labels():
    return json.load(open(os.path.join(FIX, "labels.json")))


@pytest.fixture(scope="module")
def negatives():
    return json.load(open(os.path.join(FIX, "negatives.json")))["neg"]


@pytest.fixture(scope="module")
def folds(labels):
    """fit_params on 7 gauges for each held-out gauge 1..8."""
    out = {}
    for g in range(1, 9):
        tr = [lb for lb in labels if lb["gauge"] != g]
        out[g] = mg.fit_params([load(lb["file"]) for lb in tr], tr)
    return out


def _within(read, lb):
    if read is None or read.tip_u is None:
        return False
    return (abs(read.tip_u - lb["tip"]) <= TOL and abs(read.yellow[0] - lb["seg"][2]) <= TOL
            and abs(read.yellow[1] - lb["seg"][3]) <= TOL)


def test_leave_one_gauge_out(labels, folds):
    assert len(labels) >= 60
    ok_total = n_total = 0
    for g in range(1, 9):
        held = [lb for lb in labels if lb["gauge"] == g]
        reads = [mg.read_gauge(load(lb["file"]), folds[g]) for lb in held]
        ok = sum(_within(r, lb) for r, lb in zip(reads, held))
        assert any(r is not None for r in reads), "gauge %d not detected" % g
        assert ok / len(held) >= 0.90, "fold %d: %d/%d" % (g, ok, len(held))
        ok_total += ok
        n_total += len(held)
    assert ok_total / n_total >= 0.95, "pooled %d/%d" % (ok_total, n_total)


def test_default_params_equal_full_fit(labels):
    fit = mg.fit_params([load(lb["file"]) for lb in labels], labels)
    assert fit == mg.DEFAULT_PARAMS


def test_negatives_have_no_gauge(negatives, folds):
    assert len(negatives) >= 150
    assert sum(n["t"] >= 90 for n in negatives) >= 75
    assert sum(n["mosaic"] for n in negatives) >= 20          # ranking list, nicknames mosaicked
    # every non-gauge screen type of the recording is present (windows read off the contact sheet)
    for a, b in ((4.5, 6.3), (38, 52), (64.5, 67.5), (68, 73), (73.5, 75), (7, 37), (52, 54)):
        assert any(a <= n["t"] <= b for n in negatives), (a, b)
    all_params = [mg.DEFAULT_PARAMS] + list(folds.values())
    for n in negatives:
        frame = load(n["file"])
        for p in all_params:
            assert mg.read_bar(frame, p) is None, n["file"]
            assert mg.read_gauge(frame, p) is None, n["file"]


def _first(labels, g, k=0):
    return [lb for lb in labels if lb["gauge"] == g][k]


def test_read_tip_matches_read_gauge(labels):
    for lb in labels[::6]:
        frame = load(lb["file"])
        full = mg.read_gauge(frame)
        assert full is not None
        y = int(lb["v"] * H)
        band = np.ascontiguousarray(frame[y:y + int(0.06 * H) + 12])
        box = (0.0, y / H, 1.0, (y + band.shape[0]) / H)
        tip = mg.read_tip(band, box)
        assert tip is not None and abs(tip - full.tip_u) <= 0.002


def test_zoom_in_frames_are_not_the_settled_bar(labels):
    settled = mg.read_gauge(load(_first(labels, 1)["file"]))
    reads = [mg.read_gauge(load("zoom/" + f)) for f in sorted(os.listdir(os.path.join(FIX, "zoom")))]
    assert any(r is not None for r in reads)
    for r in reads[:3]:        # first frames of gauge 1 (56.33-56.37 s): the bar is still growing
        assert not mg.same_gauge(r, settled)
    assert mg.same_gauge(settled, settled)


def test_same_gauge_tolerance(labels):
    a = mg.read_gauge(load(_first(labels, 1)["file"]))
    b = mg.read_gauge(load(_first(labels, 1, 5)["file"]))
    assert mg.same_gauge(a, b)                      # same gauge, triangle elsewhere
    nudge = lambda r, d: mg.GaugeRead(  # noqa: E731
        (r.bar[0] + d, r.bar[1] + d), r.v, tuple((n, x + d, y + d) for n, x, y in r.segments),
        (r.yellow[0] + d, r.yellow[1] + d), r.tip_u, r.button)
    assert mg.same_gauge(a, nudge(a, 0.0039))
    assert not mg.same_gauge(a, nudge(a, 0.0045))
    other = mg.read_gauge(load(_first(labels, 2)["file"]))   # different yellow
    assert not mg.same_gauge(a, other)
    assert not mg.same_gauge(a, None)


def test_zone_at_edges(labels):
    r = mg.read_gauge(load(_first(labels, 1)["file"]))
    (_, b0, b1), (_, p0, p1), (_, y0, y1), (_, q0, q1), (_, c0, c1) = r.segments
    assert mg.zone_at(r, (y0 + y1) / 2) == "yellow"
    assert mg.zone_at(r, y0) == "yellow" and mg.zone_at(r, y1) == "yellow"
    assert mg.zone_at(r, y0 - 1e-4) == "purple" and mg.zone_at(r, y1 + 1e-4) == "purple"
    assert mg.zone_at(r, p0) == "purple" and mg.zone_at(r, p0 - 1e-4) == "blue"
    assert mg.zone_at(r, q1) == "purple" and mg.zone_at(r, q1 + 1e-4) == "blue"
    assert mg.zone_at(r, b0) == "blue" and mg.zone_at(r, c1) == "blue"
    assert mg.zone_at(r, b0 - 1e-3) == "outside" and mg.zone_at(r, c1 + 1e-3) == "outside"


def test_traces_file():
    tr = json.load(open(os.path.join(FIX, "traces.json")))
    assert tr["fps"] == 60.0 and sorted(tr["gauges"]) == [str(i) for i in range(1, 9)]
    for g in tr["gauges"].values():
        assert len(g["series"]) > 50 and all(len(s) == 2 for s in g["series"])
        a, b = g["frames"]
        assert a <= g["stop_frame"] <= b and len(g["yellow"]) == 2
        assert g["yellow"][0] < g["yellow"][1]


def test_full_frames_and_scale_normalisation():
    for f in sorted(os.listdir(os.path.join(FIX, "full"))):
        img = load("full/" + f)
        base = mg.read_gauge(img)
        assert base is not None, f
        # synthetic: the same frame at the 1244 px width of a full-size GPG grab (not a live proof)
        big = cv2.resize(img, (2 * W, 2 * H), interpolation=cv2.INTER_CUBIC)
        r = mg.read_gauge(big)
        assert r is not None and mg.same_gauge(base, r)
        assert abs(r.tip_u - base.tip_u) <= 0.003


def test_fixtures_size_budget():
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(FIX) for f in fs)
    assert total <= 3 * 1024 * 1024
