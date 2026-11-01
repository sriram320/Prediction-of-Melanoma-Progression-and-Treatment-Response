"""Dataset indexing, de-duplication and lesion-level splits for the MelanoTrack ML experiments.

Sources (public):
  * ISIC 2017 Part 1/3 images + lesion masks (2,150 labelled images, 256x256 copies)
  * ISIC 2018 Task 1 images + lesion masks (2,694 images, 256x256 copies, no diagnosis labels)
  * ISIC 2017 diagnosis labels and semi-duplicate groups (RECOD 'data-depth-design' metadata)
"""
import os
import json
import numpy as np
import pandas as pd
from PIL import Image

# Paths of the original (Weeks 5-9) run; override with environment variables on another machine (e.g. Colab).
ISIC_ROOT = os.environ.get("MELANO_ISIC_ROOT", "/home/claude/data_src/isic-data")
META_ROOT = os.environ.get("MELANO_META_ROOT", "/home/claude/data_src/data-depth-design/data")
CACHE = os.environ.get("MELANO_CACHE", "/home/claude/melanotrack_ml/cache")
os.makedirs(CACHE, exist_ok=True)

DX_MAP = {"1.1.": "nevus", "3.2.": "melanoma", "1.5.": "seb_keratosis"}


def isic2017_index():
    rows = []
    for split in ("train", "val"):
        d = f"{ISIC_ROOT}/isic2017/{split}"
        for f in sorted(os.listdir(f"{d}/images")):
            iid = f[:-4]
            rows.append(dict(image_id=iid, img=f"{d}/images/{f}", mask=f"{d}/masks/{iid}_segmentation.png"))
    df = pd.DataFrame(rows)
    tr = pd.read_csv(f"{META_ROOT}/challenge-2017-train.csv", sep=";")
    va = pd.read_csv(f"{META_ROOT}/validation-challenge-2017.csv", sep=";")
    meta = pd.concat([tr, va])[["image", "diagnosis", "diagnosis_method", "age", "sex", "lesion_location", "semiduplicate"]]
    meta = meta.rename(columns={"image": "image_id", "semiduplicate": "group"})
    df = df.merge(meta, on="image_id", how="left")
    df["dx"] = df.diagnosis.map(DX_MAP)
    df["melanoma"] = (df.dx == "melanoma").astype(int)
    assert df.dx.notna().all() and all(os.path.exists(m) for m in df["mask"])
    return df


def isic2018_index():
    rows = []
    for split in ("train", "val"):
        d = f"{ISIC_ROOT}/isic2018/{split}"
        for f in sorted(os.listdir(f"{d}/images"), key=lambda s: int(s.split(".")[0])):
            rows.append(dict(image_id=f"isic18_{split}_{f[:-4]}", img=f"{d}/images/{f}", mask=f"{d}/masks/{f}"))
    return pd.DataFrame(rows)


def tiny_signature(path, n=24):
    """Normalised small grey thumbnail used to find duplicated images across the two releases."""
    g = np.asarray(Image.open(path).convert("L").resize((n, n), Image.BILINEAR), dtype=np.float32).ravel()
    g = g - g.mean()
    return g / (np.linalg.norm(g) + 1e-6)


def make_splits(seed=0):
    from sklearn.model_selection import StratifiedGroupKFold
    df = isic2017_index()
    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    fold = np.zeros(len(df), dtype=int)
    for k, (_, te) in enumerate(sgkf.split(df, df.dx, groups=df.group)):
        fold[te] = k
    df["split"] = np.where(fold == 0, "test", np.where(fold == 1, "val", "train"))
    return df


def build(seed=0):
    out = f"{CACHE}/index.json"
    df17 = make_splits(seed)
    df18 = isic2018_index()
    s17 = np.stack([tiny_signature(p) for p in df17.img])
    s18 = np.stack([tiny_signature(p) for p in df18.img])
    sim = s18 @ s17.T                       # cosine similarity of thumbnails
    best = sim.argmax(1)
    df18["dup_of"] = np.where(sim.max(1) > 0.97, df17.image_id.values[best], "")
    df18["dup_sim"] = sim.max(1)
    held = set(df17.image_id[df17.split.isin(["val", "test"])])
    # ISIC 2018 images usable for segmentation training: not a copy of any ISIC 2017 val/test image
    df18["seg_train_ok"] = ~df18.dup_of.isin(held)
    df17.to_csv(f"{CACHE}/isic2017_index.csv", index=False)
    df18.to_csv(f"{CACHE}/isic2018_index.csv", index=False)
    summary = dict(
        isic2017=len(df17), isic2018=len(df18),
        split_counts={s: df17[df17.split == s].dx.value_counts().to_dict() for s in ("train", "val", "test")},
        isic2018_duplicates_of_2017=int((df18.dup_of != "").sum()),
        isic2018_dups_of_heldout=int((~df18.seg_train_ok).sum()),
        isic2018_usable_for_seg_train=int(df18.seg_train_ok.sum()),
    )
    json.dump(summary, open(out, "w"), indent=2)
    return df17, df18, summary


def load_rgb(path, size=256):
    im = Image.open(path).convert("RGB")
    if im.size != (size, size):
        im = im.resize((size, size), Image.BILINEAR)
    return np.asarray(im)


def load_mask(path, size=256):
    m = Image.open(path).convert("L")
    if m.size != (size, size):
        m = m.resize((size, size), Image.NEAREST)
    return (np.asarray(m) > 127).astype(np.uint8)


if __name__ == "__main__":
    _, _, s = build()
    print(json.dumps(s, indent=2))
