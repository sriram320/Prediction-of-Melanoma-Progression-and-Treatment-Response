# %% [markdown]
# # MelanoTrack · Step 1 · Lesion segmentation (M3) on a GPU
#
# Retrains the Week 5 U-Net (ImageNet ResNet-34 encoder, decoder 128-64-32-16, Dice + BCE) with the team's own code
# in `training/melanotrack_ml/`, but on a GPU, at **512 px** (Week 6, Table 5) and for longer than the 5 CPU epochs
# at 192 px of Week 5. Everything else is kept the same so the results are directly comparable with the Week 5 report:
#
# * **Same test set:** the 430 held-out ISIC 2017 images (81 melanomas) of Weeks 5-9 (`splits/isic2017_splits.csv`).
# * **Same training data rule:** the ISIC 2017 training split plus the ISIC 2018 Task 1 images that are not copies of an
#   ISIC 2017 image (by id and by thumbnail similarity > 0.97, as in `src/data.py`).
# * **Same evaluation:** 8-way test-time augmentation, `keep_central_component`, Dice / IoU / thresholded Jaccard /
#   HD95 at 256 px, and the TTA agreement score as mask confidence (`src/unet.py`, `src/seg_classical.py`).
#
# The trained model is exported to **ONNX**, which the ml-service runs on a CPU with ONNX Runtime.
#
# **Before you start:** *Runtime → Change runtime type → T4 GPU*, then *Runtime → Run all*. A full run takes about
# 1.5-2 hours (about 18 GB is downloaded into Colab, not into Drive). It saves to Google Drive after every epoch: if
# Colab disconnects, run all again and it resumes. Set `QUICK_RUN = True` first for a ~5-minute check.
#
# **Data licence:** ISIC challenge data is for research use. Cite Codella et al. (2018, ISBI 2017 challenge) and
# Codella et al. (2019), arXiv:1902.03368 (ISIC 2018 challenge).

# %% [markdown]
# ## 1. Settings

# %%
QUICK_RUN = False          # True: ISIC 2017 validation images only (150), 2 epochs, to test the notebook end to end
DRIVE_DIR = "/content/drive/MyDrive/melanotrack"
REPO_URL = "https://github.com/sriram320/Prediction-of-Melanoma-Progression-and-Treatment-Response.git"
REPO_BRANCH = "main"
MODEL_NAME = "melanotrack-longitudinal"
MODEL_VERSION = "0.1.0"    # becomes ml_service/models/<MODEL_NAME>/<MODEL_VERSION>/
IMG_SIZE = 512             # Week 6, Table 5: M3 runs at 512 px
EVAL_SIZE = 256            # Week 5 scored masks at 256 px; kept for comparability (512 px is reported too)
EPOCHS = 2 if QUICK_RUN else 40
BATCH_SIZE = 8
LR_ENCODER, LR_DECODER = 3e-4, 1e-3   # as in scripts/w5_train_unet.py
SEED = 0
if QUICK_RUN:
    MODEL_VERSION = "quick-test"  # never overwrites a real run's checkpoints or exported model

# %% [markdown]
# ## 2. GPU, Google Drive, the team's code and packages

# %%
import json, os, random, subprocess, sys, time, zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import torch

print("PyTorch", torch.__version__, "| CUDA:", torch.cuda.is_available())
assert torch.cuda.is_available(), "No GPU: Runtime > Change runtime type > T4 GPU, then run again."
print(torch.cuda.get_device_name(0))

from google.colab import drive  # noqa: E402

drive.mount("/content/drive")
OUT = Path(DRIVE_DIR) / "models" / MODEL_NAME / MODEL_VERSION
CKPT = Path(DRIVE_DIR) / "checkpoints" / f"segmentation_{MODEL_VERSION}"
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

import data as team_data          # noqa: E402  (tiny_signature: duplicate detection)
import seg_classical as team_seg  # noqa: E402  (keep_central_component, dice_iou, boundary_hd95)
import unet as team_unet          # noqa: E402  (UNet, tta_confidence)

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.backends.cudnn.benchmark = True

# %% [markdown]
# ## 3. Data: download once, resize to 512 px, cache in Google Drive
#
# The archives go to the Colab disk and are deleted after use; only the resized copy (a few hundred MB) is saved to
# Drive, so later sessions skip this section.

# %%
import io

import cv2
import requests
from PIL import Image
from tqdm.auto import tqdm

ISIC = "https://isic-archive.s3.amazonaws.com/challenges"
RAW, DATA = Path("/content/raw"), Path("/content/data")
CACHE = Path(DRIVE_DIR) / "data" / f"isic2017_2018_seg_{IMG_SIZE}.zip"
SPLIT = pd.read_csv(ML / "splits" / "isic2017_splits.csv")  # image_id, dx, melanoma, group, split


def download(path: str) -> Path:
    """Downloads one archive with a progress bar; resumes a partial file."""
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


def resize_pair(image_zip: Path, mask_zip: Path, out: Path, keep=lambda stem: True) -> list[str]:
    """Writes out/images/<id>.jpg and out/masks/<id>.png at IMG_SIZE for every image that has a mask."""
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "masks").mkdir(parents=True, exist_ok=True)
    done = []
    with zipfile.ZipFile(image_zip) as zi, zipfile.ZipFile(mask_zip) as zm:
        masks = {Path(n).name.replace("_segmentation.png", ""): n for n in zm.namelist()
                 if n.endswith("_segmentation.png") and not Path(n).name.startswith("._")}
        names = sorted(n for n in zi.namelist() if n.lower().endswith(".jpg") and Path(n).stem in masks
                       and keep(Path(n).stem))
        for n in tqdm(names, desc=f"resize {image_zip.name}"):
            stem = Path(n).stem
            img = Image.open(io.BytesIO(zi.read(n)))
            img.draft("RGB", (IMG_SIZE * 2, IMG_SIZE * 2))  # fast JPEG decode at a reduced size
            arr = cv2.resize(np.asarray(img.convert("RGB")), (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
            Image.fromarray(arr).save(out / "images" / f"{stem}.jpg", quality=95)
            m = np.asarray(Image.open(io.BytesIO(zm.read(masks[stem]))).convert("L"))
            m = cv2.resize(m, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_NEAREST) > 127
            Image.fromarray((m * 255).astype(np.uint8)).save(out / "masks" / f"{stem}.png")
            done.append(stem)
    return done


def fetch(pair, out, keep=lambda stem: True):
    img_zip, mask_zip = download(pair[0]), download(pair[1])
    stems = resize_pair(img_zip, mask_zip, out, keep)
    img_zip.unlink()  # free the Colab disk
    return stems


if CACHE.exists() and not QUICK_RUN:
    print("Using the cached copy in Drive:", CACHE)
    with zipfile.ZipFile(CACHE) as z:
        z.extractall(DATA)
elif QUICK_RUN:
    fetch(("2017/ISIC-2017_Validation_Data.zip", "2017/ISIC-2017_Validation_Part1_GroundTruth.zip"),
          DATA / "isic2017")
else:
    fetch(("2017/ISIC-2017_Training_Data.zip", "2017/ISIC-2017_Training_Part1_GroundTruth.zip"), DATA / "isic2017")
    fetch(("2017/ISIC-2017_Validation_Data.zip", "2017/ISIC-2017_Validation_Part1_GroundTruth.zip"), DATA / "isic2017")
    ids_all = set(SPLIT.image_id)

    # ISIC 2018
    fetch(("2018/ISIC2018_Task1-2_Training_Input.zip", "2018/ISIC2018_Task1_Training_GroundTruth.zip"),
          DATA / "isic2018_extra", keep=lambda stem: stem not in ids_all)

    # ISIC 2014, 2015, 2016 (older challenges with segmentation masks)
    for year in ["2014", "2015", "2016"]:
        try:
            fetch((f"{year}/ISIC-{year}_Training_Data.zip", f"{year}/ISIC-{year}_Training_Part1_GroundTruth.zip"),
                  DATA / f"isic{year}_extra", keep=lambda stem: stem not in ids_all)
        except:
            print(f"Skipping ISIC {year} (not available or different format)")

    # ISIC 2019 (has Task 1 segmentation)
    try:
        fetch(("2019/ISIC_2019_Training_Input.zip", "2019/ISIC_2019_Training_GroundTruth.zip"),
              DATA / "isic2019_extra", keep=lambda stem: stem not in ids_all)
    except:
        print("Skipping ISIC 2019 (not available or different format)")

    with zipfile.ZipFile(CACHE, "w", zipfile.ZIP_STORED) as z:
        for p in DATA.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(DATA))
    print("Cached for next time:", CACHE, f"{CACHE.stat().st_size / 1e6:.0f} MB")

# Assemble the splits.
img17 = DATA / "isic2017" / "images"
SPLIT = SPLIT[SPLIT.image_id.map(lambda i: (img17 / f"{i}.jpg").exists())].copy()
SPLIT["img"] = SPLIT.image_id.map(lambda i: img17 / f"{i}.jpg")
if QUICK_RUN:  # 90 / 30 / 30 of the validation images: only checks that the code runs
    SPLIT["split"] = np.random.default_rng(SEED).permutation(["train"] * 90 + ["val"] * 30 + ["test"] * 30)[:len(SPLIT)]
    extra = []
else:
    # Collect thumbnails from the base ISIC 2017 set for duplicate detection
    s17 = np.stack([team_data.tiny_signature(p) for p in tqdm(SPLIT.img, desc="signatures 2017")])
    s17_dict = {p.stem: s for p, s in zip(SPLIT.img, s17)}

    extra = []
    years_extra = ["2018", "2014", "2015", "2016", "2019"]
    for year in years_extra:
        extra_dir = DATA / f"isic{year}_extra" / "images"
        if not extra_dir.exists():
            print(f"ISIC {year}: no images found")
            continue
        extra_paths = sorted(extra_dir.glob("*.jpg"))
        s_extra = np.stack([team_data.tiny_signature(p) for p in tqdm(extra_paths, desc=f"signatures {year}")])
        sim = (s_extra @ s17.T).max(1) if len(extra_paths) else np.zeros(0)
        new_images = [p for p, s in zip(extra_paths, sim) if s <= 0.97]
        extra.extend(new_images)
        print(f"ISIC {year}: {len(extra_paths)} total; {len(new_images)} kept after duplicate check (threshold 0.97)")

    print(f"\nTotal extra images from ISIC 2014-2019: {len(extra)}")


def mask_path(img_path: Path) -> Path:
    return img_path.parent.parent / "masks" / f"{img_path.stem}.png"


SETS = {
    "train": list(SPLIT.img[SPLIT.split == "train"]) + extra,
    "val": list(SPLIT.img[SPLIT.split == "val"]),
    "test": list(SPLIT.img[SPLIT.split == "test"]),
}
DX = dict(zip(SPLIT.image_id, SPLIT.dx))
print({k: len(v) for k, v in SETS.items()}, "| test melanomas:", int((SPLIT[SPLIT.split == "test"].dx == "melanoma").sum()))

# %% [markdown]
# ## 4. Dataset and augmentation
#
# The augmentations of `scripts/w5_train_unet.py` at 512 px: random crop, a random rotation/flip (dihedral), a small
# rotation and scaling, and brightness/contrast/colour jitter. Geometric changes move the mask with the image.

# %%
from torch.utils.data import DataLoader, Dataset
from torchvision import tv_tensors
from torchvision.io import ImageReadMode, decode_image, read_file
from torchvision.transforms import v2 as T

MEAN, STD = team_unet.MEAN.tolist(), team_unet.STD.tolist()
NORM = T.Compose([T.ToDtype(torch.float32, scale=True), T.Normalize(MEAN, STD)])


class SegData(Dataset):
    def __init__(self, paths, train: bool):
        self.paths, self.train = paths, train
        self.aug = T.Compose([
            T.RandomResizedCrop(IMG_SIZE, scale=(0.7, 1.0), ratio=(0.85, 1.18), antialias=True),
            T.RandomApply([T.RandomAffine(degrees=25, scale=(0.86, 1.16))], p=0.6),
            T.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02),
        ])

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        p = self.paths[i]
        img = decode_image(read_file(str(p)), mode=ImageReadMode.RGB)
        mask = (decode_image(read_file(str(mask_path(p))), mode=ImageReadMode.GRAY) > 127).float()
        if self.train:
            k = random.randrange(4)
            img, mask = torch.rot90(img, k, (1, 2)), torch.rot90(mask, k, (1, 2))
            if random.random() < 0.5:
                img, mask = img.flip(2), mask.flip(2)
            img, mask = self.aug(tv_tensors.Image(img.contiguous()), tv_tensors.Mask(mask.contiguous()))
        return NORM(torch.as_tensor(img)), torch.as_tensor(mask)


loaders = {
    "train": DataLoader(SegData(SETS["train"], True), batch_size=BATCH_SIZE, shuffle=True, num_workers=2,
                        pin_memory=True, drop_last=True, persistent_workers=True),
    "val": DataLoader(SegData(SETS["val"], False), batch_size=BATCH_SIZE, num_workers=2, pin_memory=True),
}

# %% [markdown]
# ## 5. Model: the team's U-Net (ResNet-34 encoder), now fully trainable
#
# Week 5 froze the stem and first encoder stage to fit a CPU budget; on a GPU everything is trained.

# %%
model = team_unet.UNet(pretrained=True, freeze_stem=False).cuda().to(memory_format=torch.channels_last)
cfg = getattr(model.enc, "pretrained_cfg", None) or getattr(model.enc, "default_cfg", {}) or {}
print("encoder weights:", cfg.get("hf_hub_id") or cfg.get("url") or cfg.get("tag") or "local file")
print(f"{sum(p.numel() for p in model.parameters()) / 1e6:.1f} M parameters")

# %% [markdown]
# ## 6. Training: BCE + Dice, AdamW (encoder 3e-4, decoder 1e-3), one-cycle schedule, mixed precision
#
# `last.pt` is saved after every epoch (for resuming), `best.pt` whenever validation Dice improves.

# %%
import torch.nn.functional as F


def dice_loss(logits, y):  # as in scripts/w5_train_unet.py
    p = torch.sigmoid(logits)
    inter = (p * y).sum((1, 2, 3))
    return 1 - ((2 * inter + 1) / (p.sum((1, 2, 3)) + y.sum((1, 2, 3)) + 1)).mean()


def batch_dice(logits, y):
    pred = (logits > 0).float()
    inter, denom = (pred * y).sum((1, 2, 3)), pred.sum((1, 2, 3)) + y.sum((1, 2, 3))
    return torch.where(denom > 0, 2 * inter / denom.clamp(min=1), torch.ones_like(denom))


enc_params = [p for p in model.enc.parameters()]
dec_params = [p for n, p in model.named_parameters() if not n.startswith("enc.")]
opt = torch.optim.AdamW([{"params": enc_params, "lr": LR_ENCODER}, {"params": dec_params, "lr": LR_DECODER}],
                        weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[LR_ENCODER, LR_DECODER], epochs=EPOCHS,
                                            steps_per_epoch=len(loaders["train"]), pct_start=0.15)
scaler = torch.amp.GradScaler("cuda")
start_epoch, best_dice, history = 0, -1.0, []
if (CKPT / "last.pt").exists() and not QUICK_RUN:
    state = torch.load(CKPT / "last.pt", map_location="cuda", weights_only=False)  # our own file
    model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"])
    sched.load_state_dict(state["sched"]); scaler.load_state_dict(state["scaler"])
    start_epoch, best_dice, history = state["epoch"] + 1, state["best_dice"], state["history"]
    print(f"Resuming after epoch {start_epoch} (best validation Dice {best_dice:.4f})")

for epoch in range(start_epoch, EPOCHS):
    t0 = time.time()
    model.train()
    losses = []
    for img, mask in tqdm(loaders["train"], desc=f"epoch {epoch + 1}/{EPOCHS}", leave=False):
        img = img.cuda(non_blocking=True).to(memory_format=torch.channels_last)
        mask = mask.cuda(non_blocking=True)
        with torch.autocast("cuda", dtype=torch.float16):
            logits = model(img)
            loss = F.binary_cross_entropy_with_logits(logits.float(), mask) + dice_loss(logits.float(), mask)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        losses.append(loss.item())
    model.eval()
    dices = []
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        for img, mask in loaders["val"]:
            dices.append(batch_dice(model(img.cuda().to(memory_format=torch.channels_last)), mask.cuda()).cpu())
    val_dice = torch.cat(dices).mean().item()
    history.append({"epoch": epoch + 1, "train_loss": float(np.mean(losses)), "val_dice": val_dice,
                    "epoch_s": time.time() - t0})
    if val_dice > best_dice:
        best_dice = val_dice
        torch.save(model.state_dict(), CKPT / "best.pt")
    torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                "scaler": scaler.state_dict(), "epoch": epoch, "best_dice": best_dice, "history": history},
               CKPT / "last.pt")
    print(f"epoch {epoch + 1:>2}: loss {np.mean(losses):.4f}  val Dice {val_dice:.4f}  best {best_dice:.4f}"
          f"  ({time.time() - t0:.0f} s)")

# %% [markdown]
# ## 7. Evaluation exactly as in Week 5 (`scripts/w5_segmentation_eval.py`)
#
# 8-way TTA (4 rotations × flip), probability maps resized to 256 px, `keep_central_component(prob > 0.5)`, and the
# team's Dice / IoU / thresholded Jaccard / HD95. Confidence = mean IoU of the 8 TTA masks with the fused mask
# (`tta_confidence`). τ_seg is tuned on the **validation** split (Youden's J for spotting masks with IoU < 0.8) and
# only reported on test; Week 5's 0.85 is reported as well.

# %%
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score, roc_curve

model.load_state_dict(torch.load(CKPT / "best.pt", map_location="cuda"))
model.eval()


@torch.no_grad()
def tta_maps(path: Path):
    """Probability maps of the 8 dihedral views at IMG_SIZE, mapped back to the original orientation: (8, H, W)."""
    x = NORM(decode_image(read_file(str(path)), mode=ImageReadMode.RGB)).unsqueeze(0).cuda()
    views = [(k, f) for k in range(4) for f in (False, True)]  # same order as unet.predict_prob
    batch = torch.cat([torch.rot90(x, k, (2, 3)).flip(3) if f else torch.rot90(x, k, (2, 3)) for k, f in views])
    with torch.autocast("cuda", dtype=torch.float16):
        p = torch.sigmoid(model(batch.to(memory_format=torch.channels_last))).float()
    back = [torch.rot90(p[i:i + 1].flip(3) if f else p[i:i + 1], -k, (2, 3)) for i, (k, f) in enumerate(views)]
    return torch.cat(back)[:, 0]


def score(mask, gt):
    d, j = team_seg.dice_iou(mask, gt)
    tp, fn = np.logical_and(mask > 0, gt > 0).sum(), np.logical_and(mask == 0, gt > 0).sum()
    tn, fp = np.logical_and(mask == 0, gt == 0).sum(), np.logical_and(mask > 0, gt == 0).sum()
    return dict(dice=d, iou=j, thr_jaccard=j if j >= 0.65 else 0.0, hd95=team_seg.boundary_hd95(mask, gt),
                sensitivity=tp / max(1, tp + fn), specificity=tn / max(1, tn + fp))


def evaluate(paths):
    rows = []
    for p in tqdm(paths, desc="evaluate", leave=False):
        maps512 = tta_maps(p)
        gt512 = np.asarray(Image.open(mask_path(p))) > 127
        maps = F.interpolate(maps512[None], size=(EVAL_SIZE, EVAL_SIZE), mode="bilinear",
                             align_corners=False)[0].cpu().numpy()
        gt = cv2.resize(gt512.astype(np.uint8), (EVAL_SIZE, EVAL_SIZE), interpolation=cv2.INTER_NEAREST)
        conf = float(team_unet.tta_confidence(maps.mean(0)[None], maps[None])[0])
        base = dict(image_id=p.stem, dx=DX.get(p.stem))
        rows.append({**base, "method": "U-Net (automatic)", **score(team_seg.keep_central_component(maps[0] > 0.5), gt),
                     "tta_conf": np.nan})
        rows.append({**base, "method": "U-Net + 8-way TTA (automatic)",
                     **score(team_seg.keep_central_component(maps.mean(0) > 0.5), gt), "tta_conf": conf})
        m512 = team_seg.keep_central_component(maps512.mean(0).cpu().numpy() > 0.5)
        rows.append({**base, "method": "U-Net + 8-way TTA, scored at 512 px", **score(m512, gt512), "tta_conf": conf})
    return pd.DataFrame(rows)


def summarise(r):
    return r.groupby("method").agg(dice_mean=("dice", "mean"), dice_median=("dice", "median"),
                                   iou_mean=("iou", "mean"), thr_jaccard=("thr_jaccard", "mean"),
                                   hd95_median=("hd95", "median"), sensitivity=("sensitivity", "mean"),
                                   specificity=("specificity", "mean"),
                                   fail_rate=("iou", lambda x: (x < 0.65).mean()))


r_val, r_test = evaluate(SETS["val"]), evaluate(SETS["test"])
summary = summarise(r_test)
week5 = pd.read_csv(ML / "results" / "week5" / "segmentation_summary.csv").set_index("method")
week5 = week5.loc[[m for m in ("U-Net (automatic)", "U-Net + 8-way TTA (automatic)") if m in week5.index]]
compare = pd.concat({"Week 5 (CPU, 192 px, 5 epochs)": week5[summary.columns],
                     f"Now (GPU, {IMG_SIZE} px, {len(history)} epochs)": summary})
print(compare.round(4).to_string())
print("\nDice by diagnosis (TTA, 256 px):")
print(r_test[r_test.method == "U-Net + 8-way TTA (automatic)"].groupby("dx").dice.mean().round(4).to_string())

# Mask confidence and τ_seg.
u_val = r_val[r_val.method == "U-Net + 8-way TTA (automatic)"]
u = r_test[r_test.method == "U-Net + 8-way TTA (automatic)"]
bad_val = (u_val.iou < 0.8).to_numpy()
if 5 <= bad_val.sum() <= len(bad_val) - 5:
    fpr, tpr, thr = roc_curve(bad_val, -u_val.tta_conf)
    tau_seg = float(-thr[np.argmax(tpr - fpr)])
else:
    tau_seg = 0.85  # too few poor masks on validation to tune: keep the Week 5 value
bad = (u.iou < 0.8).astype(int)
confidence = dict(
    tau_seg_tuned_on_val=round(tau_seg, 4),
    spearman_conf_iou=float(spearmanr(u.tta_conf, u.iou).correlation),
    auroc_conf_flags_iou_below_0_8=float(roc_auc_score(bad, -u.tta_conf)) if bad.nunique() > 1 else None,
    n_iou_below_0_8=int(bad.sum()),
    **{f"at_{name}": dict(flagged=int((u.tta_conf < t).sum()),
                          mean_iou_flagged=float(u.iou[u.tta_conf < t].mean()) if (u.tta_conf < t).any() else None,
                          mean_iou_not_flagged=float(u.iou[u.tta_conf >= t].mean()) if (u.tta_conf >= t).any() else None)
       for name, t in (("tuned", tau_seg), ("0.85", 0.85))},
)
print("\nWeek 5 confidence:", json.loads((ML / "results" / "week5" / "segmentation_confidence.json").read_text()))
print("Now:", json.dumps(confidence, indent=2))

# %% [markdown]
# ## 8. Look at the results
#
# Green: expert outline; red: model outline (TTA, 512 px). Top row: random test images; bottom row: the four worst.
# Check that the failures are plausible (hair, faint lesions, ink marks, the dermatoscope frame) rather than a bug.

# %%
import matplotlib.pyplot as plt
from scipy import ndimage


def outline(m):
    return m ^ ndimage.binary_erosion(m, iterations=2)


def show(image_id, ax, title):
    p = img17 / f"{image_id}.jpg"
    img = np.asarray(Image.open(p)).copy()
    pred = team_seg.keep_central_component(tta_maps(p).mean(0).cpu().numpy() > 0.5) > 0
    gt = np.asarray(Image.open(mask_path(p))) > 127
    img[outline(gt)] = (0, 220, 0)
    img[outline(pred)] = (230, 30, 30)
    ax.imshow(img)
    ax.set_title(title, fontsize=9)
    ax.axis("off")


fig, axes = plt.subplots(2, 4, figsize=(16, 8))
for ax, (_, row) in zip(axes[0], u.sample(4, random_state=1).iterrows()):
    show(row.image_id, ax, f"{row.dx} · Dice {row.dice:.2f} · conf {row.tta_conf:.2f}")
for ax, (_, row) in zip(axes[1], u.nsmallest(4, "iou").iterrows()):
    show(row.image_id, ax, f"{row.dx} · Dice {row.dice:.2f} · conf {row.tta_conf:.2f}")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## 9. Export to ONNX for the ml-service, and save everything to Drive
#
# The exported model takes a batch of 512×512 RGB images (scaled to 0-1, ImageNet mean/std) and returns one logit
# per pixel. The check runs the ONNX file with ONNX Runtime on the CPU and compares it with PyTorch.

# %%
import onnxruntime as ort

cpu_model = team_unet.UNet(pretrained=False, freeze_stem=False)
cpu_model.load_state_dict(torch.load(CKPT / "best.pt", map_location="cpu"))
cpu_model.eval()
dummy = torch.randn(2, 3, IMG_SIZE, IMG_SIZE)
onnx_path = OUT / "segmentation.onnx"
export_kw = dict(input_names=["image"], output_names=["logits"], opset_version=17)
try:  # the classic exporter: simple and well tested for CNNs
    torch.onnx.export(cpu_model, dummy, str(onnx_path), dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
                      dynamo=False, **export_kw)
except TypeError:  # older PyTorch without the dynamo switch
    torch.onnx.export(cpu_model, dummy, str(onnx_path), dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
                      **export_kw)
except Exception as exc:  # newer PyTorch without the classic exporter
    print("Classic ONNX exporter unavailable, using the new one:", exc)
    torch.onnx.export(cpu_model, (dummy,), str(onnx_path), dynamo=True,
                      dynamic_shapes={"x": {0: torch.export.Dim("batch", min=1, max=16)}}, **export_kw)

sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
with torch.no_grad():
    ref = cpu_model(dummy).numpy()
max_diff = float(np.abs(ref - sess.run(None, {"image": dummy.numpy()})[0]).max())
print(f"ONNX vs PyTorch max difference: {max_diff:.2e}")
assert max_diff < 1e-3, "ONNX output differs from PyTorch"
t0 = time.time()
sess.run(None, {"image": np.random.randn(8, 3, IMG_SIZE, IMG_SIZE).astype(np.float32)})
print(f"8-way TTA on Colab's CPU: {time.time() - t0:.1f} s per image (the laptop will differ)")

r_test.to_csv(OUT / "segmentation_test_per_image.csv", index=False)
meta = {
    "component": "segmentation", "file": "segmentation.onnx",
    "architecture": "U-Net, timm ResNet-34 encoder (ImageNet a1), decoder 128-64-32-16 (training/melanotrack_ml/src/unet.py)",
    "input": {"name": "image", "size": IMG_SIZE, "layout": "NCHW", "colour": "RGB", "scale": "0-1",
              "mean": MEAN, "std": STD, "resize": "cv2.INTER_AREA to a square"},
    "output": {"name": "logits", "threshold_probability": 0.5},
    "tta": "8 views: rot90 k=0..3 x horizontal flip, probabilities averaged after undoing each view",
    "postprocess": "seg_classical.keep_central_component (largest central component)",
    "confidence": "unet.tta_confidence: mean IoU of the 8 TTA masks with the fused mask",
    "tau_seg": round(tau_seg, 4),
    "data": {"train": "ISIC 2017 training split + ISIC 2018 Task 1 images that are not ISIC 2017 copies",
             "val": "ISIC 2017 validation split", "test": "the 430 ISIC 2017 test images of Weeks 5-9",
             "splits": "training/melanotrack_ml/splits/isic2017_splits.csv",
             "counts": {k: len(v) for k, v in SETS.items()}},
    "training": {"epochs": len(history), "batch_size": BATCH_SIZE, "loss": "BCE + soft Dice",
                 "optimizer": f"AdamW, one-cycle, encoder {LR_ENCODER:g} / decoder {LR_DECODER:g}", "seed": SEED,
                 "image_size": IMG_SIZE, "quick_run": QUICK_RUN, "history": history},
    "metrics_test": json.loads(summary.to_json(orient="index")), "confidence": confidence,
    "onnx_check_max_diff": max_diff, "torch_version": torch.__version__, "created": time.strftime("%Y-%m-%d %H:%M"),
    "licence_note": "Trained on ISIC challenge data (research use only). Not validated for clinical use.",
}
(OUT / "segmentation.json").write_text(json.dumps(meta, indent=2, default=float))
print("Saved to Google Drive:", OUT, sorted(p.name for p in OUT.iterdir()))

# %% [markdown]
# ## 10. Next
#
# 1. Copy the comparison table and the confidence numbers from section 7 into the chat, so we can review them.
# 2. From Google Drive, download `melanotrack/models/melanotrack-longitudinal/0.1.0/` into
#    `ml_service/models/melanotrack-longitudinal/0.1.0/` on the laptop (git-ignored: weights never go to GitHub).
# 3. Step 2 fine-tunes the melanoma classifier (EfficientNet-B3) on the same splits.
