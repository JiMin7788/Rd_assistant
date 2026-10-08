"""Train the learned die recogniser (RandomForest on colour+HOG features).

Data augmentation multiplies the small crop set and, crucially, synthesises the
BUBBLE EFFECT for every class by compositing the near-white Dice_Glow overlay --
so the model learns each type's bubbled appearance, not just the few we captured.
Honest evaluation: split ORIGINAL crops into train/test, augment TRAIN ONLY, and
report accuracy on untouched originals. Then retrain on everything and save.
"""
import os, glob
import numpy as np
import cv2
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import joblib
from rdom.perception.features import cell_features

ROOT = r"C:\dev\rdom\data\crops"
# include empty: a sparse early board shows tan background tiles the model must NOT
# force into a deck type (it was calling them Predator). Bomb stays rule-based (dark).
CLASSES = ["Predator", "Light", "Resonance", "Bubble", "Switch", "empty"]
GLOW = None
def _glow():
    global GLOW
    if GLOW is None:
        GLOW = np.array(Image.open(os.path.join(
            r"C:\dev\rdom\assets\templates\dice", "Dice_Glow3.png")).convert("RGBA"))
    return GLOW


def augment(rgb, rng, glow=True):
    """Yield realistic variants of a crop: brightness/contrast jitter, small shift,
    and (for dice only) a bubble-effect glow-overlay version. `glow=False` for empty
    tiles -- a white overlay on an empty tan tile looks like a Bubble and mislabels."""
    out = [rgb]
    h, w = rgb.shape[:2]
    for _ in range(2):
        a = rng.uniform(0.8, 1.2); b = rng.uniform(-20, 20)
        out.append(np.clip(rgb.astype(np.float32) * a + b, 0, 255).astype(np.uint8))
    M = np.float32([[1, 0, rng.randint(-3, 4)], [0, 1, rng.randint(-3, 4)]])
    out.append(cv2.warpAffine(rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT))
    if glow:
        for _ in range(2):
            g = cv2.resize(_glow(), (w, h))
            alpha = (g[:, :, 3:4].astype(np.float32) / 255.0) * rng.uniform(0.55, 0.85)
            comp = rgb.astype(np.float32) * (1 - alpha) + g[:, :, :3].astype(np.float32) * alpha
            out.append(np.clip(comp, 0, 255).astype(np.uint8))
    return out


CAP = 3000  # per-class cap: raised (from 500) after 6 real-play battles (~50k crops)
            # so we keep the diverse hard cases instead of discarding them; class_weight
            # ="balanced" handles the empty class (few hundred) imbalance. (docs/07 B.3)


def load():
    paths, y = [], []
    rng = np.random.RandomState(42)
    for lab in CLASSES:
        fs = glob.glob(os.path.join(ROOT, lab, "*.png"))
        rng.shuffle(fs)
        for fp in fs[:CAP]:
            paths.append(fp); y.append(lab)
    return paths, np.array(y)


def feats_of(paths, aug=False, rng=None):
    X, Y = [], []
    for fp, lab in paths:
        rgb = np.array(Image.open(fp).convert("RGB"))
        crops = augment(rgb, rng, glow=(lab != "empty")) if aug else [rgb]
        for c in crops:
            X.append(cell_features(c)); Y.append(lab)
    return np.array(X), np.array(Y)


if __name__ == "__main__":
    paths, y = load()
    print("originals:", {c: int((y == c).sum()) for c in CLASSES}, " total", len(y))
    rng = np.random.RandomState(0)
    tr, te = train_test_split(list(zip(paths, y)), test_size=0.25,
                              stratify=y, random_state=0)
    Xtr, Ytr = feats_of(tr, aug=True, rng=rng)
    Xte, Yte = feats_of(te, aug=False)
    print(f"train(aug)={len(Ytr)}  test(orig)={len(Yte)}")
    clf = RandomForestClassifier(n_estimators=400, class_weight="balanced",
                                 random_state=0, n_jobs=-1)
    clf.fit(Xtr, Ytr)
    pred = clf.predict(Xte)
    print("\n=== held-out (original crops) ===")
    print(classification_report(Yte, pred, digits=3, zero_division=0))
    print("confusion rows=true cols=pred", CLASSES)
    print(confusion_matrix(Yte, pred, labels=CLASSES))
    # final model on ALL data, augmented
    Xall, Yall = feats_of(list(zip(paths, y)), aug=True, rng=np.random.RandomState(1))
    clf.fit(Xall, Yall)
    joblib.dump({"model": clf, "classes": CLASSES}, r"C:\dev\rdom\data\recognizer.joblib")
    print(f"\nsaved model (trained on {len(Yall)} augmented samples)")
