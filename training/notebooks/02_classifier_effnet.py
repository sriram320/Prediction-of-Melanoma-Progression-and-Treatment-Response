# %% [markdown]
# # MelanoTrack · Step 2 · Melanoma classifier and image embedding (M5) on a GPU
#
# Fine-tunes an **EfficientNet-B3** (Week 6, Table 3 and Table 5: 300 px, 1,536 → 256-d embedding) on about 55,000
# labelled dermoscopy images, instead of the frozen ImageNet features of Week 9. It produces two things:
#
# * a **single-image melanoma probability** per visit (the contract's optional `melanoma_probability`), calibrated with
#   temperature scaling (Guo et al., 2017);
# * a **256-d image embedding** per visit, which step 3 (the GRU sequence model) uses as its image input and which the
#   out-of-distribution check of Algorithm 4 (Mahalanobis distance) is computed on.
#
# **Data:** ISIC 2019 (25,331 images: HAM10000, BCN20000 and MSK; 8 diagnoses) and ISIC 2020 (33,126 images from
# 2,056 patients), plus the ISIC 2017 images of our own splits. Nothing leaks into the test images:
#
# * The **same 430 ISIC 2017 test images** of Weeks 5-9 are held out, so the result is comparable with Week 9 (best
#   single-image AUROC 0.80). ISIC 2019 contains ISIC 2017 images under the same ids: those copies are removed, and any
#   other image whose thumbnail matches an ISIC 2017 image (cosine > 0.97, as in `src/data.py`) is removed too.
# * ISIC 2019/2020 are split 80/10/10 into train/validation/**internal test** by **lesion (2019) and patient (2020)**,
#   with near-duplicate thumbnails merged into one group, so the same lesion never sits on both sides.
#
# **Before you start:** the first run downloads about 35 GB into Colab (not into Drive) and prepares the images, which
# takes about an hour. To save GPU time, you can do that part on a free CPU runtime: set `PREPARE_ONLY = True`, *Run
# all*, then set it back to `False`, switch to *T4 GPU* and *Run all* again (the prepared images are cached in Drive,
# about 2 GB). Training then takes about 1.5 hours and saves to Drive after every epoch; if Colab disconnects, *Run all*
# again and it resumes. Set `QUICK_RUN = True` first for a ~10-minute check that reads only ~300 images.
#
# **Data licence:** ISIC 2019 and ISIC 2020 are CC BY-NC 4.0 (research, non-commercial). Cite Tschandl et al. (2018,
# HAM10000), Combalia et al. (2019, BCN20000), Codella et al. (2018) and Rotemberg et al. (2021, SIIM-ISIC 2020).

# %% [markdown]
# ## 1. Settings

# %%
QUICK_RUN = False          # True: ~300 images read straight out of the remote archives, 1 epoch, to test end to end
PREPARE_ONLY = False       # True: only download and prepare the data (works without a GPU), then stop
DRIVE_DIR = "/content/drive/MyDrive/melanotrack"
REPO_URL = "https://github.com/sriram320/Prediction-of-Melanoma-Progression-and-Treatment-Response.git"
REPO_BRANCH = "main"
MODEL_NAME = "melanotrack-longitudinal"
MODEL_VERSION = "0.1.0"    # the same folder as the segmentation model of step 1
IMG_SIZE = 300             # Week 6, Table 5: M5 runs EfficientNet-B3 at 300 px
EMB_DIM = 256              # Week 6: 1,536 -> 256
EPOCHS = 1 if QUICK_RUN else 15
BATCH_SIZE = 32
LR_BACKBONE, LR_HEAD = 2e-4, 1e-3
SEED = 0
if QUICK_RUN:
    MODEL_VERSION = "quick-test"  # never overwrites a real run's checkpoints or exported model

# %% [markdown]
# ## 2. GPU, Google Drive, the team's code and packages

# %%
import hashlib, io, json, os, random, subprocess, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import torch

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print("PyTorch", torch.__version__, "| device:", DEVICE)
if not PREPARE_ONLY:
    assert torch.cuda.is_available(), "No GPU: Runtime > Change runtime type > T4 GPU, then run again."
    print(torch.cuda.get_device_name(0))

from google.colab import drive  # noqa: E402

drive.mount("/content/drive")
OUT = Path(DRIVE_DIR) / "models" / MODEL_NAME / MODEL_VERSION
CKPT = Path(DRIVE_DIR) / "checkpoints" / f"classifier_{MODEL_VERSION}"
for p in (OUT, CKPT, Path(DRIVE_DIR) / "data"):
    p.mkdir(parents=True, exist_ok=True)

REPO = Path("/content/repo")
if REPO.exists():
    subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"], check=True)
else:
    subprocess.run(["git", "clone", "--depth", "1", "-b", REPO_BRANCH, REPO_URL, str(REPO)], check=True)
ML = REPO / "training" / "melanotrack_ml"
os.environ["MELANO_CACHE"] = "/content/cache"   # the team's modules write their cache here
sys.path.insert(0, str(ML / "src"))

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "timm", "onnx>=1.16", "onnxruntime>=1.18", "onnxscript"],
               check=True)

import data as team_data  # noqa: E402  (tiny_signature: duplicate detection)

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.backends.cudnn.benchmark = True

# %% [markdown]
# ## 3. Data: labels, images (resized to 300 px), duplicates and lesion/patient-level splits
#
# Everything is cached in Drive as `isic_cls_300.zip` (images + `index.csv`), so later sessions skip this section.

# %%
import cv2
import requests
from PIL import Image
from tqdm.auto import tqdm

ISIC = "https://isic-archive.s3.amazonaws.com/challenges"
RAW, DATA = Path("/content/raw"), Path("/content/cls")
IMG = DATA / "images"
CACHE = Path(DRIVE_DIR) / "data" / f"isic_cls_{IMG_SIZE}.zip"
SEG_CACHE = Path(DRIVE_DIR) / "data" / "isic2017_2018_seg_512.zip"   # written by notebook 01 (ISIC 2017 images)
SPLIT17 = pd.read_csv(ML / "splits" / "isic2017_splits.csv")         # image_id, dx, melanoma, group, split
CLASSES = ["MEL", "NV", "BCC", "AK", "BKL", "DF", "VASC", "SCC", "OTHER"]  # OTHER: benign without a named diagnosis
MEL = CLASSES.index("MEL")
DUP_SIM = 0.97  # thumbnail cosine similarity above which two images count as the same picture (src/data.py)


def download(path: str) -> Path:
    """Downloads one file with a progress bar; resumes a partial file."""
    RAW.mkdir(exist_ok=True)
    url, dest = f"{ISIC}/{path}", RAW / Path(path).name
    total = int(requests.head(url, timeout=60).headers["Content-Length"])
    have = dest.stat().st_size if dest.exists() else 0
    if have != total:
        headers = {"Range": f"bytes={have}-"} if have else {}
        with requests.get(url, headers=headers, stream=True, timeout=60) as r, \
                open(dest, "ab" if have else "wb") as f, \
                tqdm(total=total, initial=have, unit="B", unit_scale=True, desc=dest.name) as bar:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                bar.update(len(chunk))
    assert dest.stat().st_size == total, f"{dest.name}: incomplete download, run the cell again"
    return dest


class HttpFile(io.RawIOBase):
    """A remote file read with HTTP range requests, so QUICK_RUN can take a few images out of a 25 GB archive."""

    def __init__(self, url):
        self.url, self.pos = url, 0
        self.size = int(requests.head(url, timeout=60).headers["Content-Length"])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size or len(b) == 0:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        r = requests.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=120)
        r.raise_for_status()
        n = len(r.content)
        b[:n] = r.content
        self.pos += n
        return n


def open_archive(path: str) -> zipfile.ZipFile:
    if QUICK_RUN:
        return zipfile.ZipFile(io.BufferedReader(HttpFile(f"{ISIC}/{path}"), buffer_size=1 << 20))
    return zipfile.ZipFile(download(path))


def save_square(item):
    stem, data = item
    img = Image.open(io.BytesIO(data))
    img.draft("RGB", (IMG_SIZE * 2, IMG_SIZE * 2))  # fast JPEG decode at a reduced size
    arr = cv2.resize(np.asarray(img.convert("RGB")), (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    Image.fromarray(arr).save(IMG / f"{stem}.jpg", quality=95)


def extract(zf: zipfile.ZipFile, wanted: set, desc: str) -> int:
    """Resizes every wanted image (by file stem) of an archive into IMG."""
    IMG.mkdir(parents=True, exist_ok=True)
    names = [n for n in zf.namelist() if n.lower().endswith(".jpg") and not Path(n).name.startswith("._")
             and "__MACOSX" not in n and Path(n).stem in wanted and not (IMG / f"{Path(n).stem}.jpg").exists()]
    with ThreadPoolExecutor(4) as pool:
        for i in tqdm(range(0, len(names), 64), desc=desc):
            list(pool.map(save_square, [(Path(n).stem, zf.read(n)) for n in names[i:i + 64]]))
    return len(names)


def done_with(path: str):
    if not QUICK_RUN:
        (RAW / Path(path).name).unlink(missing_ok=True)  # free the Colab disk


def label_tables():
    """One row per image: image_id, source, dx, group (lesion or patient), sex, age, site, split (2017 only)."""
    gt19 = pd.read_csv(download("2019/ISIC_2019_Training_GroundTruth.csv"))
    meta19 = pd.read_csv(download("2019/ISIC_2019_Training_Metadata.csv"))
    t19 = gt19.merge(meta19, on="image", how="left")
    onehot = t19[CLASSES[:-1]]
    assert (onehot.sum(axis=1) == 1).all(), "ISIC 2019: expected exactly one diagnosis per image"
    t19 = pd.DataFrame(dict(image_id=t19.image, source="isic2019", dx=onehot.idxmax(axis=1),
                            group="19:" + t19.lesion_id.fillna(t19.image), sex=t19.sex, age=t19.age_approx,
                            site=t19.anatom_site_general))
    gt20 = pd.read_csv(download("2020/ISIC_2020_Training_GroundTruth_v2.csv"))
    dx20 = {"melanoma": "MEL", "nevus": "NV", "seborrheic keratosis": "BKL", "lentigo NOS": "BKL",
            "lichenoid keratosis": "BKL", "solar lentigo": "BKL"}
    t20 = pd.DataFrame(dict(image_id=gt20.image_name, source="isic2020", dx=gt20.diagnosis.map(dx20).fillna("OTHER"),
                            group="20:" + gt20.patient_id, sex=gt20.sex, age=gt20.age_approx,
                            site=gt20.anatom_site_general_challenge))
    assert ((t20.dx == "MEL") == (gt20.target == 1)).all(), "ISIC 2020: melanoma labels disagree with 'target'"
    dups = pd.read_csv(download("2020/ISIC_2020_Training_Duplicates.csv"))
    t20 = t20[~t20.image_id.isin(dups.image_name_2)]  # ISIC's own list of duplicated pictures: keep one of each
    in17 = t19.image_id.str.replace("_downsampled", "", regex=False).isin(set(SPLIT17.image_id))
    print(f"ISIC 2019: {len(t19)} images, {int(in17.sum())} are ISIC 2017 images by id (removed, ours are used)")
    t19 = t19[~in17]
    t17 = pd.DataFrame(dict(image_id=SPLIT17.image_id, source="isic2017",
                            dx=SPLIT17.dx.map({"melanoma": "MEL", "nevus": "NV", "seb_keratosis": "BKL"}),
                            group="17:" + SPLIT17.group, split=SPLIT17.split))
    assert t17.dx.notna().all()
    return pd.concat([t17, t19, t20], ignore_index=True)


def quick_subset(t):
    """QUICK_RUN: a few images per source, with melanomas in every split."""
    r = np.random.default_rng(SEED)
    parts = []
    for src, n in (("isic2017", 40), ("isic2019", 150), ("isic2020", 150)):
        s = t[t.source == src]
        if src == "isic2017":
            parts.append(s.groupby(["split", "dx"], group_keys=False).apply(lambda g: g.sample(min(len(g), 6), random_state=SEED)))
            continue
        mel = s[s.dx == "MEL"].sample(n // 3, random_state=SEED)
        parts.append(pd.concat([mel, s[s.dx != "MEL"].sample(n - len(mel), random_state=SEED)]))
    return pd.concat(parts, ignore_index=True)


def part_path(src):
    return Path(DRIVE_DIR) / "data" / f"isic_cls_{IMG_SIZE}_part_{src}.zip"


def keep_part(src, ids):
    """Saves one finished source to Drive, so a disconnected session does not prepare it again."""
    if QUICK_RUN:
        return
    tmp = part_path(src).with_name(part_path(src).name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for i in tqdm(sorted(ids), desc=f"save {src} to Drive"):
            if (IMG / f"{i}.jpg").exists():
                z.write(IMG / f"{i}.jpg", f"{i}.jpg")
    tmp.replace(part_path(src))  # written under a temporary name first: a half-written part is never used


def fetch_images(t):
    IMG.mkdir(parents=True, exist_ok=True)
    jobs = [("isic2017", ("2017/ISIC-2017_Training_Data.zip", "2017/ISIC-2017_Validation_Data.zip")),
            ("isic2019", ("2019/ISIC_2019_Training_Input.zip",)), ("isic2020", ("2020/ISIC_2020_Training_JPEG.zip",))]
    for src, archives in jobs:
        ids = set(t.image_id[t.source == src])
        if part_path(src).exists() and not QUICK_RUN:
            with zipfile.ZipFile(part_path(src)) as z:
                z.extractall(IMG)
            print(f"{src}: already prepared in an earlier session ({part_path(src).name})")
            continue
        if src == "isic2017" and SEG_CACHE.exists():  # the ISIC 2017 images notebook 01 already prepared (512 px)
            with zipfile.ZipFile(SEG_CACHE) as z:
                extract(z, ids, "ISIC 2017 (from notebook 01's cache)")
        else:
            for path in archives:
                with open_archive(path) as z:
                    extract(z, ids, Path(path).name)
                done_with(path)
        print(f"{src}: {sum((IMG / f'{i}.jpg').exists() for i in ids)} of {len(ids)} images ready")
        keep_part(src, ids)


class Groups:
    """Union-find over group names: near-duplicate pictures end up in one group."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def near_duplicates(paths):
    """All pairs (i < j) of images whose thumbnails have cosine similarity > DUP_SIM."""
    sig = np.stack([team_data.tiny_signature(p) for p in tqdm(paths, desc="thumbnails")]).astype(np.float32)
    s = torch.from_numpy(sig).to(DEVICE)
    pairs = []
    for a in range(0, len(s), 4096):
        ii, jj = torch.nonzero(s[a:a + 4096] @ s.T > DUP_SIM, as_tuple=True)
        keep = ii + a < jj
        pairs.append(torch.stack([ii[keep] + a, jj[keep]], 1).cpu())
    return torch.cat(pairs).numpy()


def assign_splits(t):
    """Drops copies of ISIC 2017 images, merges near-duplicates, and splits ISIC 2019/2020 by group 80/10/10."""
    t = t.reset_index(drop=True)
    pairs = near_duplicates([IMG / f"{i}.jpg" for i in t.image_id])
    is17 = (t.source == "isic2017").to_numpy()
    i, j = pairs[:, 0], pairs[:, 1]
    cross = is17[i] != is17[j]
    drop = set(np.where(is17[i], j, i)[cross])  # the ISIC 2019/2020 side of a match with an ISIC 2017 image
    both17 = is17[i] & is17[j]
    split17 = t.split.to_numpy()
    leak = both17 & (split17[i] != split17[j]) & ((split17[i] == "test") | (split17[j] == "test"))
    drop |= set(np.where(split17[i] == "test", j, i)[leak])  # keep the test image, drop its copy elsewhere
    print(f"near-duplicate pairs: {len(pairs)}; ISIC 2019/2020 copies of ISIC 2017 images removed: {int(cross.sum())}; "
          f"ISIC 2017 copies of a test image outside the test split removed: {int(leak.sum())}")
    g = Groups()
    for a, b in pairs[~is17[i] & ~is17[j]]:
        g.union(t.group[a], t.group[b])
    t = t.drop(index=sorted(drop)).copy()
    other = t.source != "isic2017"
    t.loc[other, "group"] = t.group[other].map(g.find)
    sizes = t.group[other].value_counts()
    print("largest ISIC 2019/2020 groups (images):", sizes.head(5).to_dict())
    fold = t.group[other].map(lambda s: int(hashlib.md5(s.encode()).hexdigest(), 16) % 10)
    k = 2 if QUICK_RUN else 1  # QUICK_RUN: 60/20/20, so the tiny test split still has melanomas
    t.loc[other, "split"] = np.where(fold < k, "test", np.where(fold < 2 * k, "val", "train"))
    t["label"] = t.dx.map(CLASSES.index)
    return t


if CACHE.exists() and not QUICK_RUN:
    print("Using the cached copy in Drive:", CACHE)
    with zipfile.ZipFile(CACHE) as z:
        z.extractall(DATA)
    INDEX = pd.read_csv(DATA / "index.csv")
else:
    table = label_tables()
    if QUICK_RUN:
        table = quick_subset(table)
    fetch_images(table)
    have = table.image_id.map(lambda i: (IMG / f"{i}.jpg").exists())
    print(f"images found: {int(have.sum())} of {len(table)}")
    assert have.mean() > 0.99, "many images are missing: check the downloads above"
    INDEX = assign_splits(table[have])
    INDEX.to_csv(DATA / "index.csv", index=False)
    if not QUICK_RUN:
        tmp = CACHE.with_name(CACHE.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for p in tqdm(sorted(DATA.rglob("*")), desc="cache to Drive"):
                if p.is_file():
                    z.write(p, p.relative_to(DATA))
        tmp.replace(CACHE)
        for src in ("isic2017", "isic2019", "isic2020"):
            part_path(src).unlink(missing_ok=True)  # the full cache replaces the per-source parts
        print("Cached for next time:", CACHE, f"{CACHE.stat().st_size / 1e6:.0f} MB")

print(INDEX.groupby(["split", "source"]).dx.value_counts().unstack(fill_value=0).to_string())
assert set(INDEX.image_id[(INDEX.source == "isic2017") & (INDEX.split == "test")]) <= set(
    SPLIT17.image_id[SPLIT17.split == "test"]), "an ISIC 2017 image changed split"
for name, part in INDEX.groupby("split"):
    others = INDEX[INDEX.split != name]
    assert not set(part.group) & set(others.group), f"a lesion/patient group crosses the {name} split"
if PREPARE_ONLY:
    raise RuntimeError("Data is ready in Drive. Set PREPARE_ONLY = False, switch to a T4 GPU and Run all again. "
                       "(This stop is intended.)")

# %% [markdown]
# ## 4. Dataset and augmentation
#
# Random crop (50-100 % of the image), a random rotation/flip (dihedral, as dermoscopy has no "up"), a small rotation
# and scaling, and brightness/contrast/colour jitter. Validation and test images are only resized.

# %%
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from torchvision.io import ImageReadMode, decode_image, read_file
from torchvision.transforms import v2 as T

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]  # ImageNet, as timm's efficientnet_b3.ra2_in1k
NORM = T.Compose([T.ToDtype(torch.float32, scale=True), T.Normalize(MEAN, STD)])
AUG = T.Compose([
    T.RandomResizedCrop(IMG_SIZE, scale=(0.5, 1.0), ratio=(0.8, 1.25), antialias=True),
    T.RandomApply([T.RandomAffine(degrees=20, scale=(0.9, 1.1))], p=0.5),
    T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.15, hue=0.03),
])


class ClsData(Dataset):
    def __init__(self, df, train: bool):
        self.paths = [str(IMG / f"{i}.jpg") for i in df.image_id]
        self.labels = df.label.to_numpy()
        self.train = train

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        img = decode_image(read_file(self.paths[i]), mode=ImageReadMode.RGB)
        if self.train:
            img = torch.rot90(img, random.randrange(4), (1, 2))
            if random.random() < 0.5:
                img = img.flip(2)
            img = AUG(img.contiguous())
        return NORM(img), int(self.labels[i])


SETS = {name: INDEX[INDEX.split == name].reset_index(drop=True) for name in ("train", "val", "test")}
SETS["val17"] = SETS["val"][SETS["val"].source == "isic2017"].reset_index(drop=True)
SETS["test17"] = SETS["test"][SETS["test"].source == "isic2017"].reset_index(drop=True)      # the 430 of Weeks 5-9
SETS["test_int"] = SETS["test"][SETS["test"].source != "isic2017"].reset_index(drop=True)    # internal ISIC 2019/2020
SETS["val_int"] = SETS["val"][SETS["val"].source != "isic2017"].reset_index(drop=True)
print({k: f"{len(v)} images, {int((v.dx == 'MEL').sum())} melanomas" for k, v in SETS.items()})
WORKERS = min(4, os.cpu_count() or 2)
train_loader = DataLoader(ClsData(SETS["train"], True), batch_size=BATCH_SIZE, shuffle=True, num_workers=WORKERS,
                          pin_memory=True, drop_last=True, persistent_workers=True)

# %% [markdown]
# ## 5. Model: EfficientNet-B3 (ImageNet) → 256-d embedding → 9 diagnoses
#
# Training on all nine diagnoses (not only melanoma vs the rest) gives the network more to learn from, as in the
# winning SIIM-ISIC 2020 solution (Ha et al., 2020); the melanoma probability is the MEL output.

# %%
import timm
import torch.nn as nn


class Classifier(nn.Module):
    def __init__(self, pretrained: bool):
        super().__init__()
        self.backbone = timm.create_model("efficientnet_b3.ra2_in1k", pretrained=pretrained, num_classes=0)
        self.drop = nn.Dropout(0.3)
        self.proj = nn.Linear(self.backbone.num_features, EMB_DIM)
        self.head = nn.Linear(EMB_DIM, len(CLASSES))

    def forward(self, x):
        emb = self.proj(self.drop(self.backbone(x)))
        return self.head(F.gelu(emb)), emb


model = Classifier(pretrained=True).to(DEVICE).to(memory_format=torch.channels_last)
print(f"{sum(p.numel() for p in model.parameters()) / 1e6:.1f} M parameters")

# %% [markdown]
# ## 6. Training: cross-entropy, AdamW (backbone 2e-4, head 1e-3), one-cycle schedule, mixed precision
#
# `last.pt` is saved after every epoch (for resuming), `best.pt` whenever the validation melanoma AUROC improves.

# %%
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

AMP = dict(device_type=DEVICE, dtype=torch.float16, enabled=DEVICE == "cuda")
VIEWS = [(k, f) for k in range(4) for f in (False, True)]  # 8-way TTA: 4 rotations x horizontal flip


@torch.no_grad()
def predict(df, tta: bool):
    """Mean logits and mean embeddings over the views: (N, 9), (N, 256)."""
    model.eval()
    loader = DataLoader(ClsData(df, False), batch_size=BATCH_SIZE, num_workers=WORKERS, pin_memory=True)
    logits, embs = [], []
    for x, _ in loader:
        x = x.to(DEVICE, non_blocking=True)
        lsum, esum = 0, 0
        for k, f in VIEWS if tta else VIEWS[:1]:
            v = torch.rot90(x, k, (2, 3))
            v = v.flip(3) if f else v
            with torch.autocast(**AMP):
                l, e = model(v.contiguous(memory_format=torch.channels_last))
            lsum, esum = lsum + l.float(), esum + e.float()
        n = len(VIEWS) if tta else 1
        logits.append((lsum / n).cpu())
        embs.append((esum / n).cpu())
    return torch.cat(logits).numpy(), torch.cat(embs).numpy()


def p_mel(logits, temperature=1.0):
    return torch.softmax(torch.from_numpy(logits) / temperature, 1)[:, MEL].numpy()


def is_mel(df):
    return (df.dx == "MEL").to_numpy().astype(int)


backbone = list(model.backbone.parameters())
head = list(model.proj.parameters()) + list(model.head.parameters())
opt = torch.optim.AdamW([{"params": backbone, "lr": LR_BACKBONE}, {"params": head, "lr": LR_HEAD}], weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[LR_BACKBONE, LR_HEAD], epochs=EPOCHS,
                                            steps_per_epoch=len(train_loader), pct_start=0.1)
scaler = torch.amp.GradScaler(DEVICE, enabled=DEVICE == "cuda")
start_epoch, best_auc, history = 0, -1.0, []
if (CKPT / "last.pt").exists() and not QUICK_RUN:
    state = torch.load(CKPT / "last.pt", map_location=DEVICE, weights_only=False)  # our own file
    model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"])
    sched.load_state_dict(state["sched"]); scaler.load_state_dict(state["scaler"])
    start_epoch, best_auc, history = state["epoch"] + 1, state["best_auc"], state["history"]
    print(f"Resuming after epoch {start_epoch} (best validation AUROC {best_auc:.4f})")

for epoch in range(start_epoch, EPOCHS):
    t0 = time.time()
    model.train()
    losses = []
    for x, y in tqdm(train_loader, desc=f"epoch {epoch + 1}/{EPOCHS}", leave=False):
        x = x.to(DEVICE, non_blocking=True).contiguous(memory_format=torch.channels_last)
        y = y.to(DEVICE, non_blocking=True)
        with torch.autocast(**AMP):
            logits, _ = model(x)
            loss = F.cross_entropy(logits.float(), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        losses.append(loss.item())
    lv, _ = predict(SETS["val"], tta=False)
    pv, yv = p_mel(lv), is_mel(SETS["val"])
    v17 = (SETS["val"].source == "isic2017").to_numpy()
    auc, auc17 = roc_auc_score(yv, pv), roc_auc_score(yv[v17], pv[v17])
    acc = float((lv.argmax(1) == SETS["val"].label.to_numpy()).mean())
    history.append({"epoch": epoch + 1, "train_loss": float(np.mean(losses)), "val_auroc_mel": auc,
                    "val17_auroc_mel": auc17, "val_accuracy_9class": acc, "epoch_s": time.time() - t0})
    if auc > best_auc:
        best_auc = auc
        torch.save(model.state_dict(), CKPT / "best.pt")
    torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                "scaler": scaler.state_dict(), "epoch": epoch, "best_auc": best_auc, "history": history},
               CKPT / "last.pt")
    print(f"epoch {epoch + 1:>2}: loss {np.mean(losses):.4f}  val AUROC {auc:.4f} (ISIC 2017 val {auc17:.4f})  "
          f"9-class acc {acc:.3f}  best {best_auc:.4f}  ({time.time() - t0:.0f} s)")

# %% [markdown]
# ## 7. Evaluation
#
# 8-way TTA (logits averaged), then **temperature scaling** fitted on the validation split. Results on:
#
# * the **430 ISIC 2017 test images** of Weeks 5-9, next to the Week 9 single-image baselines (same images; Week 9 used
#   frozen ImageNet features + logistic regression trained on ISIC 2017 only). The operating threshold is chosen on the
#   ISIC 2017 validation split (Youden's J), as in Week 9;
# * the **internal ISIC 2019/2020 test split** (unseen lesions and patients), with subgroups by sex, age, body site
#   and source (groups with fewer than 10 melanomas or 10 benign lesions are not scored).

# %%
model.load_state_dict(torch.load(CKPT / "best.pt", map_location=DEVICE, weights_only=True))
pred = {name: predict(SETS[name], tta=True) for name in ("val", "test")}
pred1 = {name: predict(SETS[name], tta=False) for name in ("val", "test")}


def fit_temperature(logits, labels):
    log_t = torch.zeros(1, requires_grad=True)
    lg, lb = torch.from_numpy(logits), torch.from_numpy(labels)
    opt_t = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)

    def closure():
        opt_t.zero_grad()
        loss = F.cross_entropy(lg / log_t.exp(), lb)
        loss.backward()
        return loss

    opt_t.step(closure)
    return float(log_t.exp())


def ece(y, p, bins=10):
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(y[idx == b].mean() - p[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def youden(y, p):
    fpr, tpr, thr = roc_curve(y, p)
    return float(thr[np.argmax(tpr - fpr)])


def binary_metrics(y, p, thr, boot=2000):
    fpr, tpr, _ = roc_curve(y, p)
    r = np.random.default_rng(SEED)
    aucs = []
    for _ in range(boot):
        k = r.integers(0, len(y), len(y))
        if 0 < y[k].sum() < len(k):
            aucs.append(roc_auc_score(y[k], p[k]))
    sens, spec = float((p[y == 1] >= thr).mean()), float((p[y == 0] < thr).mean())
    return dict(auroc=roc_auc_score(y, p), auroc_lo=float(np.percentile(aucs, 2.5)), auroc_hi=float(np.percentile(aucs, 97.5)),
                auprc=average_precision_score(y, p), sens_at_spec80=float(tpr[fpr <= 0.2].max()),
                sensitivity=sens, specificity=spec, balanced_acc=(sens + spec) / 2, ece=ece(y, p), n=len(y), n_mel=int(y.sum()))


TEMP = fit_temperature(pred["val"][0], SETS["val"].label.to_numpy())
print(f"temperature fitted on validation: {TEMP:.3f}")
part = {"val17": SETS["val"].source.eq("isic2017").to_numpy(), "test17": SETS["test"].source.eq("isic2017").to_numpy()}
part["val_int"], part["test_int"] = ~part["val17"], ~part["test17"]
P = {name: p_mel(pred["val" if name.startswith("val") else "test"][0], TEMP)[part[name]] for name in part}
P1 = {name: p_mel(pred1["val" if name.startswith("val") else "test"][0])[part[name]] for name in part}
Y = {name: is_mel(SETS[name]) for name in part}
THR17, THR_INT = youden(Y["val17"], P["val17"]), youden(Y["val_int"], P["val_int"])
THR17_1 = youden(Y["val17"], P1["val17"])

cols = ["auroc", "auroc_lo", "auroc_hi", "auprc", "sens_at_spec80", "sensitivity", "specificity", "balanced_acc"]
week9 = pd.read_csv(ML / "results" / "week9" / "baselines.csv").set_index("model")[cols]
week9.index = "Week 9 · " + week9.index + " (frozen)"
now = pd.DataFrame({
    "Now · EfficientNet-B3 fine-tuned (1 view)": binary_metrics(Y["test17"], P1["test17"], THR17_1),
    "Now · EfficientNet-B3 fine-tuned (8-view TTA, calibrated)": binary_metrics(Y["test17"], P["test17"], THR17),
}).T
compare17 = pd.concat([week9, now[cols]])
print(f"ISIC 2017 test ({len(Y['test17'])} images, {Y['test17'].sum()} melanomas), melanoma vs benign:")
print(compare17.round(4).to_string())

internal = binary_metrics(Y["test_int"], P["test_int"], THR_INT)
print("\nInternal ISIC 2019/2020 test (unseen lesions/patients):", json.dumps({k: round(v, 4) for k, v in internal.items()}))
raw_ece = ece(Y["test_int"], p_mel(pred["test"][0])[part["test_int"]])
print(f"calibration error (ECE) on the internal test: {raw_ece:.4f} before, {internal['ece']:.4f} after temperature scaling")

t17 = SETS["test17"]
by_dx = {}
for dx in ("NV", "BKL"):
    m = ((t17.dx == "MEL") | (t17.dx == dx)).to_numpy()
    by_dx[dx] = float(roc_auc_score(Y["test17"][m], P["test17"][m]))
print("ISIC 2017 test AUROC, melanoma vs nevus / vs seborrhoeic keratosis:", {k: round(v, 4) for k, v in by_dx.items()})

ti = SETS["test_int"].assign(p=P["test_int"], y=Y["test_int"])
ti["age_band"] = pd.cut(ti.age, [-1, 39, 59, 120], labels=["<40", "40-59", "60+"]).astype(object)
rows = []
for dim in ("sex", "age_band", "site", "source"):
    for value, g in ti.groupby(ti[dim].fillna("unknown").astype(str)):
        ok = g.y.sum() >= 10 and (1 - g.y).sum() >= 10
        rows.append(dict(dimension=dim, group=value, n=len(g), melanomas=int(g.y.sum()),
                         auroc=roc_auc_score(g.y, g.p) if ok else np.nan,
                         sensitivity=float((g.p[g.y == 1] >= THR_INT).mean()) if ok else np.nan,
                         specificity=float((g.p[g.y == 0] < THR_INT).mean()) if ok else np.nan))
subgroups = pd.DataFrame(rows)
print("\nInternal test by subgroup (NaN = too few to score):")
print(subgroups.round(4).to_string(index=False))

# %% [markdown]
# ## 8. Out-of-distribution score (Algorithm 4, M11)
#
# Mahalanobis distance of an image's embedding from the training embeddings (Ledoit-Wolf covariance, 10,000 training
# images). τ_OOD is the 99th percentile on validation, so about 1 % of normal dermoscopy images are flagged. As a sanity
# check, pictures that are clearly not dermoscopy (noise, flat colours, stripes) should almost all be flagged.

# %%
from sklearn.covariance import LedoitWolf

fit_df = SETS["train"].sample(min(10000, len(SETS["train"])), random_state=SEED)
_, emb_fit = predict(fit_df, tta=True)
lw = LedoitWolf().fit(emb_fit)
MU, PREC = lw.location_.astype(np.float32), lw.precision_.astype(np.float32)


def mahalanobis(e):
    d = e - MU
    return np.sqrt(np.einsum("ij,jk,ik->i", d, PREC, d))


d_val, d_test = mahalanobis(pred["val"][1]), mahalanobis(pred["test"][1])
TAU_OOD = float(np.percentile(d_val, 99))


@torch.no_grad()
def embed_arrays(arrays):
    model.eval()
    x = torch.stack([NORM(torch.from_numpy(a).permute(2, 0, 1).contiguous()) for a in arrays]).to(DEVICE)
    out = []
    for k, f in VIEWS:
        v = torch.rot90(x, k, (2, 3))
        v = v.flip(3) if f else v
        with torch.autocast(**AMP):
            out.append(model(v.contiguous(memory_format=torch.channels_last))[1].float())
    return torch.stack(out).mean(0).cpu().numpy()


r = np.random.default_rng(SEED)
yy, xx = np.mgrid[:IMG_SIZE, :IMG_SIZE]
odd = [r.integers(0, 256, (IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8) for _ in range(16)]
odd += [np.full((IMG_SIZE, IMG_SIZE, 3), r.integers(0, 256, 3), np.uint8) for _ in range(16)]
odd += [np.stack([((xx // w) % 2) * 255] * 3, -1).astype(np.uint8) for w in (4, 8, 16, 32, 64, 128)]
odd += [np.stack([xx * 255 // IMG_SIZE, yy * 255 // IMG_SIZE, np.full_like(xx, 128)], -1).astype(np.uint8)]
d_odd = mahalanobis(embed_arrays(odd))
ood = dict(tau_ood=TAU_OOD, flagged_val=float((d_val > TAU_OOD).mean()),
           flagged_test17=float((d_test[part["test17"]] > TAU_OOD).mean()),
           flagged_test_int=float((d_test[part["test_int"]] > TAU_OOD).mean()),
           flagged_not_dermoscopy=float((d_odd > TAU_OOD).mean()), n_not_dermoscopy=len(odd))
print(json.dumps({k: round(v, 4) for k, v in ood.items()}, indent=2))

# %% [markdown]
# ## 9. Look at the results
#
# Left: ROC on the 430 ISIC 2017 test images (the dot is the threshold chosen on validation). Right: reliability on the
# internal test after temperature scaling (points near the diagonal = the probabilities mean what they say).

# %%
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fpr, tpr, _ = roc_curve(Y["test17"], P["test17"])
axes[0].plot(fpr, tpr, lw=2, label=f"EfficientNet-B3 fine-tuned (AUROC {roc_auc_score(Y['test17'], P['test17']):.3f})")
axes[0].plot([0, 1], [0, 1], color="grey", lw=1, ls="--")
axes[0].scatter([1 - now.iloc[1].specificity], [now.iloc[1].sensitivity], s=60, zorder=3, label="validation threshold")
axes[0].set(xlabel="1 - specificity", ylabel="sensitivity", title=f"ISIC 2017 test · Week 9 best AUROC {week9.auroc.max():.3f}")
axes[0].legend(loc="lower right")
edges = np.linspace(0, 1, 11)
idx = np.minimum((P["test_int"] * 10).astype(int), 9)
pts = [(P["test_int"][idx == b].mean(), Y["test_int"][idx == b].mean(), (idx == b).sum()) for b in range(10) if (idx == b).sum() >= 5]
axes[1].plot([0, 1], [0, 1], color="grey", lw=1, ls="--")
axes[1].plot([p[0] for p in pts], [p[1] for p in pts], marker="o", lw=2)
for x_, y_, n_ in pts:
    axes[1].annotate(str(n_), (x_, y_), textcoords="offset points", xytext=(4, -10), fontsize=8)
axes[1].set(xlabel="predicted melanoma probability", ylabel="observed melanoma rate", xlim=(0, 1), ylim=(0, 1),
            title=f"Internal test reliability · ECE {internal['ece']:.3f} (number of images per bin)")
plt.tight_layout()
plt.savefig(OUT / "classifier_figures.png", dpi=120)
plt.show()

# %% [markdown]
# ## 10. Export to ONNX for the ml-service, and save everything to Drive
#
# The exported model takes a batch of 300×300 RGB images (scaled to 0-1, ImageNet mean/std) and returns `logits`
# (9 diagnoses), `embedding` (256-d) and `features` (the last 1,536-channel feature map). The ml-service averages
# logits and embeddings over the 8 TTA views, divides the logits by the temperature and takes the MEL softmax output.
#
# **Saliency (Grad-CAM, Selvaraju et al., 2017) without a gradient engine:** the head after the feature map is
# global-average-pool → linear → GELU → linear, so the gradient of the melanoma logit with respect to each channel is
# `proj_weight.T @ (gelu'(embedding) * head_weight[MEL]) / (h·w)`. The ml-service computes the map in numpy from
# `features` and the two weight matrices in `classifier_cam.npz`; the cell checks it against PyTorch's autograd.
# The OOD statistics go to `classifier_ood.npz`.

# %%
import onnxruntime as ort
from scipy.special import erf

cpu_model = Classifier(pretrained=False)
cpu_model.load_state_dict(torch.load(CKPT / "best.pt", map_location="cpu", weights_only=True))
cpu_model.eval()


class Export(nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):
        feats = self.m.backbone.forward_features(x)
        emb = self.m.proj(self.m.backbone.forward_head(feats))  # dropout is off in eval mode
        return self.m.head(F.gelu(emb)), emb, feats


export_model = Export(cpu_model).eval()
dummy = torch.randn(2, 3, IMG_SIZE, IMG_SIZE)
onnx_path = OUT / "classifier.onnx"
axes_ = {"image": {0: "batch"}, "logits": {0: "batch"}, "embedding": {0: "batch"}, "features": {0: "batch"}}
export_kw = dict(input_names=["image"], output_names=["logits", "embedding", "features"], opset_version=17)
try:  # the classic exporter: simple and well tested for CNNs
    torch.onnx.export(export_model, dummy, str(onnx_path), dynamic_axes=axes_, dynamo=False, **export_kw)
except TypeError:  # older PyTorch without the dynamo switch
    torch.onnx.export(export_model, dummy, str(onnx_path), dynamic_axes=axes_, **export_kw)
except Exception as exc:  # newer PyTorch without the classic exporter
    print("Classic ONNX exporter unavailable, using the new one:", exc)
    torch.onnx.export(export_model, (dummy,), str(onnx_path), dynamo=True,
                      dynamic_shapes={"x": {0: torch.export.Dim("batch", min=1, max=16)}}, **export_kw)

sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
with torch.no_grad():
    ref = [t.numpy() for t in cpu_model(dummy)]
got = sess.run(None, {"image": dummy.numpy()})
max_diff = float(max(np.abs(a - b).max() for a, b in zip(ref, got[:2])))
print(f"ONNX vs PyTorch max difference: {max_diff:.2e}")
assert max_diff < 1e-3, "ONNX output differs from PyTorch"

W_PROJ = cpu_model.proj.weight.detach().numpy()            # (256, 1536)
W_MEL = cpu_model.head.weight.detach().numpy()[MEL]        # (256,)


def gradcam_numpy(features, embedding):
    gelu_grad = 0.5 * (1 + erf(embedding / np.sqrt(2))) + embedding * np.exp(-embedding ** 2 / 2) / np.sqrt(2 * np.pi)
    alpha = (gelu_grad * W_MEL) @ W_PROJ / (features.shape[2] * features.shape[3])   # (batch, 1536)
    return np.maximum(np.einsum("bc,bchw->bhw", alpha, features), 0)


x = dummy.clone()
feats = cpu_model.backbone.forward_features(x)
feats.retain_grad()
cpu_model.head(F.gelu(cpu_model.proj(cpu_model.backbone.forward_head(feats))))[:, MEL].sum().backward()
cam_torch = torch.relu((feats.grad.mean((2, 3), keepdim=True) * feats).sum(1)).detach().numpy()
cam_np = gradcam_numpy(got[2], got[1])
cam_diff = float(np.abs(cam_np - cam_torch).max() / (np.abs(cam_torch).max() + 1e-12))
print(f"Grad-CAM, numpy from ONNX outputs vs PyTorch autograd: relative difference {cam_diff:.2e}")
assert cam_diff < 1e-2, "numpy Grad-CAM disagrees with autograd"
t0 = time.time()
sess.run(None, {"image": np.random.randn(8, 3, IMG_SIZE, IMG_SIZE).astype(np.float32)})
print(f"8-way TTA on Colab's CPU: {time.time() - t0:.1f} s per image (the laptop will differ)")

np.savez(OUT / "classifier_ood.npz", mean=MU, precision=PREC, tau_ood=np.float32(TAU_OOD))
np.savez(OUT / "classifier_cam.npz", proj_weight=W_PROJ, head_weight_mel=W_MEL)
per_image = SETS["test"][["image_id", "source", "dx"]].assign(
    p_melanoma=p_mel(pred["test"][0], TEMP), ood_distance=d_test)
per_image.to_csv(OUT / "classifier_test_per_image.csv", index=False)
counts = {name: {"images": len(SETS[name]), "melanomas": int((SETS[name].dx == "MEL").sum())}
          for name in ("train", "val", "test17", "test_int")}
meta = {
    "component": "classifier", "file": "classifier.onnx",
    "architecture": f"timm efficientnet_b3.ra2_in1k (ImageNet), dropout 0.3, linear {model.backbone.num_features} -> "
                    f"{EMB_DIM} (embedding), GELU, linear {EMB_DIM} -> {len(CLASSES)}",
    "input": {"name": "image", "size": IMG_SIZE, "layout": "NCHW", "colour": "RGB", "scale": "0-1",
              "mean": MEAN, "std": STD, "resize": "cv2.INTER_AREA to a square (whole image, no crop)"},
    "outputs": {"logits": {"classes": CLASSES, "melanoma_index": MEL}, "embedding": {"dim": EMB_DIM},
                "features": {"shape": list(got[2].shape[1:]), "use": "Grad-CAM"}},
    "saliency": {"method": "Grad-CAM on the melanoma logit", "file": "classifier_cam.npz",
                 "formula": "alpha = (gelu'(embedding) * head_weight_mel) @ proj_weight / (h*w); "
                            "cam = relu(sum_c alpha_c * features_c); gelu is the exact (erf) form",
                 "check_relative_diff": cam_diff},
    "tta": "8 views: rot90 k=0..3 x horizontal flip; logits and embeddings averaged over the views",
    "temperature": TEMP,
    "melanoma_probability": "softmax(mean_logits / temperature)[melanoma_index]",
    "thresholds_youden_val": {"isic2017": THR17, "isic2019_2020": THR_INT},
    "ood": {"file": "classifier_ood.npz", "distance": "Mahalanobis on the mean embedding (Ledoit-Wolf)",
            **ood},
    "data": {"train": "ISIC 2019 + ISIC 2020 (80 % of lesions/patients) + ISIC 2017 training split",
             "val": "ISIC 2019/2020 (10 %) + ISIC 2017 validation split",
             "test17": "the 430 ISIC 2017 test images of Weeks 5-9", "test_int": "ISIC 2019/2020 (10 %)",
             "dedup": f"ISIC 2017 ids removed from ISIC 2019; thumbnails with cosine > {DUP_SIM} removed or grouped",
             "splits": "training/melanotrack_ml/splits/isic2017_splits.csv + md5(group) % 10", "counts": counts},
    "training": {"epochs": len(history), "batch_size": BATCH_SIZE, "loss": "cross-entropy over 9 diagnoses",
                 "optimizer": f"AdamW, one-cycle, backbone {LR_BACKBONE:g} / head {LR_HEAD:g}", "seed": SEED,
                 "image_size": IMG_SIZE, "quick_run": QUICK_RUN, "history": history},
    "metrics_test17": json.loads(compare17.to_json(orient="index")),
    "metrics_test_int": internal, "ece_test_int_before_temperature": raw_ece,
    "auroc_test17_by_benign_type": by_dx, "subgroups_test_int": json.loads(subgroups.to_json(orient="records")),
    "onnx_check_max_diff": max_diff, "torch_version": torch.__version__, "created": time.strftime("%Y-%m-%d %H:%M"),
    "licence_note": "Trained on ISIC 2017-2020 challenge data (CC BY-NC, research use only). Not validated for "
                    "clinical use.",
}
(OUT / "classifier.json").write_text(json.dumps(meta, indent=2, default=float))
print("Saved to Google Drive:", OUT, sorted(p.name for p in OUT.iterdir()))

# %% [markdown]
# ## 11. Next
#
# 1. Copy the ISIC 2017 comparison table, the internal test line, the subgroup table and the OOD numbers into the chat.
# 2. From Google Drive, download `melanotrack/models/melanotrack-longitudinal/0.1.0/` again into
#    `ml_service/models/melanotrack-longitudinal/0.1.0/` (it now also holds `classifier.onnx`, `classifier.json` and
#    `classifier_ood.npz`).
# 3. Step 3 trains the GRU sequence model on the 256-d embeddings of simulated visit sequences.
