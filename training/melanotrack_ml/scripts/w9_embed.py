"""Week-9: frozen ImageNet embeddings for real ISIC 2017 images (baselines) or simulated visit images.

usage: python w9_embed.py real <model>      -> cache/emb/real_<model>.npz
       python w9_embed.py visits <model>    -> cache/emb/visits_<model>.npz
"""
import sys, os, time
import numpy as np
import pandas as pd
import torch
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb
from unet import load_timm_backbone, MEAN, STD

torch.set_num_threads(int(os.environ.get("THREADS", 1)))
EMB = "/home/claude/melanotrack_ml/cache/emb"
os.makedirs(EMB, exist_ok=True)
MODELS = {
    "resnet50": ("resnet50", "resnet50_a1_0-14fe96d1.pth", 224),
    "effb0": ("efficientnet_b0", "efficientnet_b0_ra-3dd342df.pth", 224),
    "effb3": ("efficientnet_b3", "efficientnet_b3_ra2-cf984f9c.pth", 256),
    "swin_t": ("swin_tiny_patch4_window7_224", "swin_tiny_patch4_window7_224.pth", 224),
}


@torch.no_grad()
def embed(model, imgs, size):
    x = np.stack([cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA) for im in imgs]).astype(np.float32) / 255
    x = torch.from_numpy(((x - MEAN) / STD).transpose(0, 3, 1, 2).copy())
    f1 = model(x)
    if os.environ.get("NOFLIP"):
        return f1.numpy().astype(np.float32)
    f2 = model(torch.flip(x, dims=(3,)))          # horizontal-flip view
    return ((f1 + f2) / 2).numpy().astype(np.float32)


if __name__ == "__main__":
    what, key = sys.argv[1], sys.argv[2]
    name, ckpt, size = MODELS[key]
    model, missing, _ = load_timm_backbone(name, ckpt, num_classes=0)
    assert len(missing) == 0, missing
    model.eval()
    if what == "real":
        df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
        ids, paths = df.image_id.tolist(), df.img.tolist()
        loader = load_rgb
    else:
        v = pd.read_csv("/home/claude/melanotrack_ml/cache/seq/visits.csv", usecols=["image_id", "version", "t"])
        ids = [f"{a}_{b}_v{c}" for a, b, c in zip(v.image_id, v.version, v.t)]
        paths = [f"/home/claude/melanotrack_ml/cache/seq/img/{i}.jpg" for i in ids]
        loader = lambda p: cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
    feats, t0 = [], time.time()
    for b in range(0, len(paths), 32):
        feats.append(embed(model, [loader(p) for p in paths[b:b + 32]], size))
        if b % 640 == 0:
            print(key, b, f"{time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(f"{EMB}/{what}_{key}.npz", ids=np.array(ids), X=np.concatenate(feats))
    print("done", key, np.concatenate(feats).shape, f"{time.time() - t0:.0f}s", flush=True)
