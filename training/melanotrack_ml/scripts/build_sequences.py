"""Build simulated 4-visit sequences for every ISIC 2017 lesion (a 'progressing' and a 'stable' version)
and run the full per-visit pipeline: U-Net segmentation -> SIFT skin registration to baseline -> descriptors.

Descriptors are measured in each visit's OWN frame (no resampling); the registration to visit 1 is used to
convert sizes to baseline pixels (lengths x s, area x s^2, border gradient / s, s = registration scale).
Resampling a follow-up into the baseline frame blurs the image (bilinear) and makes the warped mask outline
jagged (nearest neighbour), which biases perimeter-based shape and texture measures at every follow-up.

Outputs (cache/seq/):
  visits.csv       one row per (lesion, version, visit) with pipeline features (f_*), oracle features (o_*,
                   test split only), true change parameters, segmentation Dice, registration scale and error
  img/*.jpg        the simulated visit images (input to the Week-9 image encoders; WRITE_IMG=1)
Env: SPLITS=test or train,val (default all), OUT=<csv name>, PROCS, LIMIT, WRITE_IMG
"""
import sys, os, time, json, zlib
import numpy as np
import pandas as pd
import cv2
cv2.setNumThreads(1)
import torch
from multiprocessing import Pool
from scipy import ndimage as ndi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb, load_mask
from sequences import sequence_params, simulate_sequence, true_follow_to_base
from register import reg_sift, warp_to_ref, plausible
from features import describe
from seg_classical import keep_central_component, dice_iou

SEQ = "/home/claude/melanotrack_ml/cache/seq"
os.makedirs(f"{SEQ}/img", exist_ok=True)
_model = None


def _init():
    global _model
    torch.set_num_threads(1)
    from unet import UNet
    _model = UNet(pretrained=False)
    _model.load_state_dict(torch.load("/home/claude/melanotrack_ml/cache/unet_r34.pt", map_location="cpu"))
    _model.eval()


def segment(imgs):
    from unet import predict_prob
    probs, _ = predict_prob(_model, imgs, tta=False)
    return [keep_central_component(p > 0.5) for p in probs]


def reg_error(A, A_true, base_true_mask, warped_true_mask, rng, n=300):
    far = ~ndi.binary_dilation((base_true_mask > 0) | (warped_true_mask > 0), iterations=20)
    far[:12] = far[-12:] = False; far[:, :12] = far[:, -12:] = False
    ys, xs = np.nonzero(far)
    if len(xs) < 20:
        ys, xs = np.nonzero(np.ones_like(far))
    idx = rng.choice(len(xs), size=min(n, len(xs)), replace=False)
    P = np.stack([xs[idx], ys[idx]], 1).astype(np.float64)
    inv = cv2.invertAffineTransform(A_true)
    Q = (inv[:, :2] @ P.T).T + inv[:, 2]
    Pe = (A[:, :2] @ Q.T).T + A[:, 2]
    return float(np.linalg.norm(Pe - P, axis=1).mean())


SIZE_LEN = ("eq_diameter", "max_diameter", "perimeter")


def native_descriptors(img, mask, A):
    """Descriptors in the visit's own frame, sizes converted to baseline-frame pixels with the scale of A."""
    f = describe(img, mask) if mask.sum() > 30 else None
    if f is None:
        return None, 1.0
    sc = float(np.sqrt(abs(np.linalg.det(A[:, :2])))) if plausible(A) else 1.0
    f["area"] *= sc ** 2
    for k in SIZE_LEN:
        f[k] *= sc
    f["border_sharpness"] /= sc
    return f, sc


def run(job):
    row, version, oracle = job
    seed = zlib.crc32(f"{row['image_id']}|{version}".encode())
    rng = np.random.default_rng(seed)
    img, gt = load_rgb(row["img"]), load_mask(row["mask"])
    params = sequence_params(rng, progress=(version == "prog"))
    visits = simulate_sequence(img, gt, params, rng)
    preds = segment([v["img"] for v in visits])
    base = visits[0]
    out = []
    for v, pm in zip(visits, preds):
        r = dict(image_id=row["image_id"], version=version, split=row["split"], dx=row["dx"], melanoma=int(row["melanoma"]),
                 t=v["t"], month=v["month"], progress=params["progress"], G=params["G"], asym_param=params["asym"],
                 colour_param=params["colour"], true_area_px=v["true_area_px"], true_rel_area_final=v["true_rel_area"],
                 seg_dice=dice_iou(pm, v["true_mask"])[0], pred_area_raw=float(pm.sum()))
        if os.environ.get("WRITE_IMG"):
            fn = f"{SEQ}/img/{row['image_id']}_{version}_v{v['t']}.jpg"
            cv2.imwrite(fn, cv2.cvtColor(v["img"], cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
        A_true = true_follow_to_base(base["C"], v["C"])
        if v["t"] == 0:
            A = np.array([[1, 0, 0], [0, 1, 0]], float)
            r.update(reg_err=0.0, reg_ok=True, reg_fallback=False, reg_inliers=-1)
        else:
            if pm.sum() > 30 and preds[0].sum() > 30:
                A, info = reg_sift(base["img"], v["img"], preds[0], pm, region="skin")
            else:
                A, info = np.array([[1, 0, 0], [0, 1, 0]], float), dict(ok=False, fallback=True, inliers=0)
            _, wtm = warp_to_ref(v["img"], v["true_mask"], A_true, (256, 256))
            r.update(reg_err=reg_error(A, A_true, base["true_mask"], wtm, rng), reg_ok=bool(info.get("ok", False)),
                     reg_fallback=bool(info.get("fallback", False)), reg_inliers=int(info.get("inliers", 0)))
        f, sc = native_descriptors(v["img"], pm, A)
        r.update(reg_scale=sc, true_scale=float(np.sqrt(abs(np.linalg.det(A_true[:, :2])))),
                 true_area_native=float((v["true_mask"] > 0).sum()))
        if f:
            r.update({f"f_{k}": val for k, val in f.items()})
        if oracle:
            fo, _ = native_descriptors(v["img"], v["true_mask"] > 0, A_true)
            if fo:
                r.update({f"o_{k}": val for k, val in fo.items()})
        out.append(r)
    return out


if __name__ == "__main__":
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
    if os.environ.get("SPLITS"):
        df = df[df.split.isin(os.environ["SPLITS"].split(","))]
    limit = int(os.environ.get("LIMIT", 0))
    if limit:
        df = df.groupby("split").head(limit)
    jobs = [(r._asdict() if hasattr(r, "_asdict") else r.to_dict(), ver, r["split"] == "test")
            for _, r in df.iterrows() for ver in ("prog", "stable")]
    t0 = time.time()
    rows = []
    with Pool(int(os.environ.get("PROCS", 2)), initializer=_init) as pool:
        for k, res in enumerate(pool.imap_unordered(run, jobs, chunksize=4)):
            rows.extend(res)
            if k % 100 == 0:
                print(f"{k}/{len(jobs)} sequences, {time.time() - t0:.0f}s", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(f"{SEQ}/{os.environ.get('OUT', 'visits.csv')}", index=False)
    print("done", len(out), f"{time.time() - t0:.0f}s", flush=True)
