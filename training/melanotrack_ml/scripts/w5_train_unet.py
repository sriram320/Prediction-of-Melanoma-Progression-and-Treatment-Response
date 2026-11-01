"""Train the U-Net (ResNet-34 encoder) for lesion segmentation on CPU within a time budget."""
import sys, os, time, json
import numpy as np
import pandas as pd
import cv2
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb, load_mask
from unet import UNet, MEAN, STD

torch.set_num_threads(2)
torch.manual_seed(0)
np.random.seed(0)
OUT = "/home/claude/melanotrack_ml/results/week5"
CK = "/home/claude/melanotrack_ml/cache/unet_r34.pt"
S_LOAD, S = 224, 192
MAX_MIN = float(os.environ.get("MAX_MIN", 32))
EPOCHS = int(os.environ.get("EPOCHS", 12))
BS = 16


def load_set(rows):
    X = np.stack([cv2.resize(load_rgb(p), (S_LOAD, S_LOAD), interpolation=cv2.INTER_AREA) for p in rows.img])
    Y = np.stack([cv2.resize(load_mask(m), (S_LOAD, S_LOAD), interpolation=cv2.INTER_NEAREST) for m in rows["mask"]])
    return X, Y


def augment(x, y, rng):
    # random crop, dihedral transform, small affine, colour jitter
    i, j = rng.integers(0, S_LOAD - S + 1, 2)
    x, y = x[i:i + S, j:j + S], y[i:i + S, j:j + S]
    k = rng.integers(4)
    x, y = np.rot90(x, k), np.rot90(y, k)
    if rng.random() < 0.5:
        x, y = x[:, ::-1], y[:, ::-1]
    if rng.random() < 0.6:
        M = cv2.getRotationMatrix2D((S / 2, S / 2), rng.uniform(-25, 25), np.exp(rng.uniform(-0.15, 0.15)))
        x = cv2.warpAffine(np.ascontiguousarray(x), M, (S, S), borderMode=cv2.BORDER_REFLECT101)
        y = cv2.warpAffine(np.ascontiguousarray(y), M, (S, S), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT101)
    x = x.astype(np.float32) / 255.0
    x = x * (1 + rng.uniform(-0.15, 0.15, 3)) + rng.uniform(-0.08, 0.08)
    x = np.clip(x, 0, 1) ** np.exp(rng.uniform(-0.2, 0.2))
    return np.ascontiguousarray(x, dtype=np.float32), np.ascontiguousarray(y)


def norm(x):
    return torch.from_numpy(((x - MEAN) / STD).astype(np.float32).transpose(0, 3, 1, 2).copy())


def dice_loss(logits, y):
    p = torch.sigmoid(logits)
    inter = (p * y).sum((1, 2, 3))
    return 1 - ((2 * inter + 1) / (p.sum((1, 2, 3)) + y.sum((1, 2, 3)) + 1)).mean()


def evaluate(model, X, Y):
    model.eval()
    dices = []
    with torch.no_grad():
        for b in range(0, len(X), 32):
            xb = np.stack([cv2.resize(x, (S, S), interpolation=cv2.INTER_AREA) for x in X[b:b + 32]]).astype(np.float32) / 255
            p = torch.sigmoid(model(norm(xb)))[:, 0].numpy() > 0.5
            for pi, yi in zip(p, Y[b:b + 32]):
                yi = cv2.resize(yi, (S, S), interpolation=cv2.INTER_NEAREST) > 0
                s = pi.sum() + yi.sum()
                dices.append(2 * (pi & yi).sum() / s if s else 1.0)
    return float(np.mean(dices))


if __name__ == "__main__":
    d17 = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
    d18 = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2018_index.csv")
    uniq18 = d18[d18.dup_of.isna() | (d18.dup_of.astype(str) == "") | (d18.dup_of.astype(str) == "nan")]
    tr = pd.concat([d17[d17.split == "train"][["img", "mask"]], uniq18[["img", "mask"]]])
    va = d17[d17.split == "val"]
    t0 = time.time()
    Xtr, Ytr = load_set(tr)
    Xva, Yva = load_set(va)
    print(f"train {len(Xtr)} val {len(Xva)} loaded in {time.time() - t0:.0f}s", flush=True)
    model = UNet(pretrained=True)
    print("encoder keys missing:", model.n_missing, flush=True)
    enc_params = [p for p in model.enc.parameters() if p.requires_grad]
    dec_params = [p for n, p in model.named_parameters() if not n.startswith("enc.")]
    opt = torch.optim.AdamW([{"params": enc_params, "lr": 3e-4}, {"params": dec_params, "lr": 1e-3}], weight_decay=1e-4)
    steps_per_epoch = int(np.ceil(len(Xtr) / BS))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[3e-4, 1e-3], total_steps=EPOCHS * steps_per_epoch, pct_start=0.15)
    rng = np.random.default_rng(0)
    hist, best = [], -1
    start = time.time()
    for ep in range(EPOCHS):
        model.train()
        perm = rng.permutation(len(Xtr))
        tl, te0 = 0.0, time.time()
        for b in range(steps_per_epoch):
            idx = perm[b * BS:(b + 1) * BS]
            xs, ys = zip(*(augment(Xtr[i], Ytr[i], rng) for i in idx))
            xb = norm(np.stack(xs)); yb = torch.from_numpy(np.stack(ys)[:, None].astype(np.float32))
            logits = model(xb)
            loss = F.binary_cross_entropy_with_logits(logits, yb) + dice_loss(logits, yb)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tl += loss.item()
        vd = evaluate(model, Xva, Yva)
        hist.append(dict(epoch=ep + 1, train_loss=tl / steps_per_epoch, val_dice=vd, epoch_s=time.time() - te0))
        print(hist[-1], flush=True)
        if vd > best:
            best = vd
            torch.save(model.state_dict(), CK)
        elapsed = (time.time() - start) / 60
        if elapsed + (time.time() - te0) / 60 > MAX_MIN:
            print("time budget reached", flush=True)
            break
    json.dump(dict(history=hist, best_val_dice=best, n_train=len(Xtr), n_val=len(Xva), input=S,
                   epochs_run=len(hist), minutes=(time.time() - start) / 60), open(f"{OUT}/unet_training.json", "w"), indent=2)
