"""Train the gear-deck recognisers from data/crops_gear (2026-10-07 recording).

Labels: data/crops_gear/y_fixed.npy (type per crop: cluster labels + model-audited
fixes + hand fixes from the run sheets) and pip.npy (hand-counted once per stable
run, propagated across the run; 0 = unlabelled). See _gear/ for the labelling steps.

  data/gear_type.joblib  RandomForest on perception.features.cell_features
  data/gear_pip.joblib   ExtraTrees on perception.gear.pip_features
"""
import os, sys
import numpy as np
import cv2
import joblib
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rdom.perception.features import cell_features
from rdom.perception.gear import pip_features

D = r"C:\dev\rdom\data\crops_gear"
names = np.load(os.path.join(D, "feats.npz"))["names"]
y = np.load(os.path.join(D, "y_fixed.npy"), allow_pickle=True)
pip = np.load(os.path.join(D, "pip.npy"))


def crop(n):
    return cv2.cvtColor(cv2.imread(os.path.join(D, "_raw", n + ".png")), cv2.COLOR_BGR2RGB)


lab = np.where(y != "")[0]
print("type: computing features for", len(lab))
X = np.array([cell_features(crop(names[i])) for i in lab]); Y = list(y[lab].astype(str))
# later sessions: features were saved at collection time, labels from the run sheets
for tag in ("s2", "s3"):
    z = np.load(os.path.join(D, f"feats_{tag}.npz")); yt = np.load(os.path.join(D, f"y_{tag}.npy"), allow_pickle=True)
    m = yt != ""
    X = np.concatenate([X, z["X"][m]]); Y += list(yt[m].astype(str))
    print(f"  + {tag}: {m.sum()}")
tm = RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1,
                            random_state=0).fit(X, np.array(Y))
joblib.dump(tm, r"C:\dev\rdom\data\gear_type.joblib", compress=3)

print("saved type model", tm.classes_, "(pips: tools/train_gear_pip_cnn.py)")
