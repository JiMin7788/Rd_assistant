"""Check the support-deck perception assets against the saved H1 data.

  python tools/check_support_assets.py [--data-dir <repo>/data] [--out-dir <tmp>/rdom_lvbox]

Prints one line per check; exit 0 (exit 1 only on an exception). Missing inputs give n=0 / 0/0.
  score: n=<n> correct=<c> none=<k> wrong=<w>   read_score on data/digits/score/<value>_<any>.png crops
  score lobby: none=<k>/<n>                      read_score is None on data/support_frames/manual lobby frames
  deck bar: support <t>/<n> gear-false <g>/<m>   detect_support_deck is True on <t> of <n> support battle frames
                                                 (sup*/<t>.png, is_battle, no power panel) and False on <g> of
                                                 <m> gear battle frames (manual/*.png, is_battle)
  deck bar excluded: <k> (<file>, ...)           support frames not counted: 'panel' (power panel open) or
                                                 'bar hidden' (not is_battle); at most 10 names, then '...'
  power cards: <k>/<n>                           panel_*.png frames with Growth, Alignment and Resonance found
                                                 on three different buttons
  lv box: drew <n> overlays to <dir>             LV_BOX drawn at every buy button of each panel frame
                                                 (lvbox_<game>_<frame>.png), to check by eye

Run on C:/dev/rdom/data (2026-10-29):
  score: n=42 correct=38 none=4 wrong=0
  score lobby: none=1/1
  deck bar: support 181/181 gear-false 5/5
  deck bar excluded: 0
  power cards: 5/5
  lv box: drew 5 overlays to <tmp>/rdom_lvbox
"""
import argparse, glob, os, sys, tempfile
import cv2

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.perception import board, gear, score, support


def check_score(data_dir):
    """Crops are cut with SCORE_BOX, so the frame fed to read_score is the crop itself laid out at its box position."""
    n = correct = none = wrong = 0
    for p in sorted(glob.glob(os.path.join(data_dir, "digits", "score", "*.png"))):
        value = os.path.basename(p).split("_", 1)[0]
        img = cv2.imread(p)
        if img is None or not value.isdigit():            # 0-byte / corrupt file or no value prefix
            continue
        n += 1
        r = score.read_score(_frame_for_crop(img))
        if r is None:
            none += 1
        elif r == int(value):
            correct += 1
        else:
            wrong += 1
    return f"score: n={n} correct={correct} none={none} wrong={wrong}"


def _frame_for_crop(crop_bgr):
    """Blank RGB frame (9:16, 2224 high like the H1 frames) with the crop pasted at SCORE_BOX, so read_score cuts it back out."""
    import numpy as np
    h = 2224; W = round(h * 9 / 16)
    u0, v0, u1, v1 = score.SCORE_BOX
    x0, y0, x1, y1 = int(u0 * W), int(v0 * h), int(u1 * W), int(v1 * h)
    f = np.zeros((h, W, 3), np.uint8)
    f[y0:y1, x0:x1] = cv2.resize(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB), (x1 - x0, y1 - y0))
    return f


def check_score_lobby(data_dir):
    n = none = 0
    for p in sorted(glob.glob(os.path.join(data_dir, "support_frames", "manual", "*.png"))):
        bgr = cv2.imread(p)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if board.is_battle(rgb):
            continue
        n += 1
        if score.read_score(rgb) is None:
            none += 1
    return f"score lobby: none={none}/{n}"


def _read_rgb(p):
    bgr = cv2.imread(p)
    return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _support_frames(data_dir):
    """Battle frames of the support games: data/support_frames/sup*/<t>.png (panel_*.png are not these)."""
    return [p for p in sorted(glob.glob(os.path.join(data_dir, "support_frames", "sup*", "*.png")))
            if not os.path.basename(p).startswith("panel_")]


def _panel_frames(data_dir):
    return sorted(glob.glob(os.path.join(data_dir, "support_frames", "sup*", "panel_*.png")))


def _game_frame(p):
    return os.path.basename(os.path.dirname(p)), os.path.splitext(os.path.basename(p))[0]


def check_deck_bar(data_dir, max_names=10):
    """Two lines: support frames that show the support deck bar, gear frames that must not, and the excluded support frames."""
    n = t = 0
    excluded = []
    for p in _support_frames(data_dir):
        rgb = _read_rgb(p)
        if rgb is None:
            continue
        name = f"{_game_frame(p)[0]}/{os.path.basename(p)}"
        if gear.ui_state(rgb)["power_panel"]:             # the open power panel covers the deck bar
            excluded.append(f"{name}: panel")
        elif not board.is_battle(rgb):
            excluded.append(f"{name}: bar hidden")
        else:
            n += 1
            t += bool(support.detect_support_deck(rgb))
    m = g = 0
    for p in sorted(glob.glob(os.path.join(data_dir, "support_frames", "manual", "*.png"))):
        rgb = _read_rgb(p)
        if rgb is None or not board.is_battle(rgb):
            continue
        m += 1
        g += not support.detect_support_deck(rgb)
    names = excluded[:max_names] + (["..."] if len(excluded) > max_names else [])
    tail = f" ({', '.join(names)})" if names else ""
    return f"deck bar: support {t}/{n} gear-false {g}/{m}\ndeck bar excluded: {len(excluded)}{tail}"


def check_power_cards(data_dir):
    """Panel frames in which Growth, Alignment and Resonance are all found, each on its own button."""
    n = k = 0
    for p in _panel_frames(data_dir):
        rgb = _read_rgb(p)
        if rgb is None:
            continue
        n += 1
        found = list(support.power_cards(rgb).values())
        k += all(b is not None for b in found) and len({tuple(b) for b in found}) == 3
    return f"power cards: {k}/{n}"


def draw_lv_boxes(data_dir, out_dir):
    """Draw LV_BOX at every buy button of each panel frame -> out_dir/lvbox_<game>_<frame>.png, to check by eye."""
    n = 0
    if support.LV_BOX is not None:
        for p in _panel_frames(data_dir):
            rgb = _read_rgb(p)
            if rgb is None:
                continue
            h = rgb.shape[0]; W = gear._content_w(rgb)
            out = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            du0, dv0, du1, dv1 = support.LV_BOX
            for u, v in gear.power_buttons(rgb):
                cv2.rectangle(out, (int((u + du0) * W), int((v + dv0) * h)), (int((u + du1) * W), int((v + dv1) * h)),
                              (0, 0, 255), 1)
            os.makedirs(out_dir, exist_ok=True)
            game, frame = _game_frame(p)
            cv2.imwrite(os.path.join(out_dir, f"lvbox_{game}_{frame}.png"), out)
            n += 1
    return f"lv box: drew {n} overlays to {out_dir}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out-dir", default=os.path.join(tempfile.gettempdir(), "rdom_lvbox"))   # overlays are never written into data/
    a = ap.parse_args(argv)
    try:
        print(check_score(a.data_dir))
        print(check_score_lobby(a.data_dir))
        print(check_deck_bar(a.data_dir))
        print(check_power_cards(a.data_dir))
        print(draw_lv_boxes(a.data_dir, a.out_dir))
    except Exception as e:                                # AI-NOTE: only an exception is a failure; bad reads are reported in the lines
        print(f"error: {e!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
