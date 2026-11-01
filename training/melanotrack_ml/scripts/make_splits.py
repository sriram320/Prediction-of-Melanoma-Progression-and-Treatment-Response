"""Builds the ISIC 2017 split used for MelanoTrack training from the team's saved test set.

test  = the 430 test images of Weeks 5-9 (results/week9/baseline_scores.npz; identical to week 5's U-Net rows)
val   = 430 images from the rest, stratified by diagnosis and grouped by RECOD near-duplicate group (seed 0)
train = the remaining 1,290
Checks that no near-duplicate group crosses the test boundary (no leakage into test).

The groups come from RECOD's metadata (github.com/learningtitans/data-depth-design, branch master, data/).
Re-running src/data.py make_splits() with today's scikit-learn does not reproduce the original split, so the saved
test ids are used instead. Output: splits/isic2017_splits.csv (committed).

  python scripts/make_splits.py <recod data dir> results splits/isic2017_splits.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

meta_dir, results_dir, out_csv = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
DX_MAP = {"1.1.": "nevus", "3.2.": "melanoma", "1.5.": "seb_keratosis"}

tr = pd.read_csv(meta_dir / "challenge-2017-train.csv", sep=";")
va = pd.read_csv(meta_dir / "validation-challenge-2017.csv", sep=";")
df = pd.concat([tr, va])[["image", "diagnosis", "semiduplicate"]].rename(
    columns={"image": "image_id", "semiduplicate": "group"}).sort_values("image_id").reset_index(drop=True)
df["dx"] = df.diagnosis.map(DX_MAP)
assert df.dx.notna().all() and df.image_id.is_unique and len(df) == 2150

z = np.load(results_dir / "week9" / "baseline_scores.npz")
test_ids = set(z["ids"].tolist())
seg = pd.read_csv(results_dir / "week5" / "segmentation_raw.csv")
assert test_ids == set(seg.image_id), "week 5 and week 9 test sets differ"
assert test_ids <= set(df.image_id)
df["split"] = np.where(df.image_id.isin(test_ids), "test", "")
y_saved = dict(zip(z["ids"].tolist(), z["y"].tolist()))
assert all((df.dx[df.image_id == i].iloc[0] == "melanoma") == bool(v) for i, v in y_saved.items()), "labels differ"

crossing = df.groupby("group").split.agg(lambda s: s.eq("test").any() and s.ne("test").any())
print("near-duplicate groups crossing the test boundary:", int(crossing.sum()))
leak = df[df.group.isin(crossing[crossing].index) & (df.split != "test")]
if len(leak):
    print("moving", len(leak), "near-duplicates of test images out of train/val (marked 'excluded')")
    df.loc[leak.index, "split"] = "excluded"

rest = df[df.split == ""]
k = round(len(rest) / 430)  # folds of ~430 images
fold = np.zeros(len(rest), dtype=int)
for f, (_, idx) in enumerate(StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=0)
                             .split(rest, rest.dx, groups=rest.group)):
    fold[idx] = f
df.loc[rest.index, "split"] = np.where(fold == 0, "val", "train")
df["melanoma"] = (df.dx == "melanoma").astype(int)
print(df.groupby(["split", "dx"]).size().unstack(fill_value=0))
df[["image_id", "dx", "melanoma", "group", "split"]].to_csv(out_csv, index=False)
print("written", out_csv)
