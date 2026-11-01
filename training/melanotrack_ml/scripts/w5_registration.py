"""Week-5 registration experiment on simulated follow-up visits with known ground truth.

For every held-out test image (real baseline) two follow-ups are simulated:
  A) acquisition change only (rotation, scale, shift, illumination, blur, noise);
  B) the same plus real-looking lesion growth (area x1.2-1.6, asymmetric) and colour change.
Each registration method maps the follow-up back to the baseline frame. We measure
  * residual alignment error on skin away from the lesion (px),
  * lesion-mask overlap after alignment (A only),
  * how much of the true growth survives alignment (B only).
"""
import sys, os, json, time
import numpy as np
import pandas as pd
import cv2
cv2.setNumThreads(1)
from scipy import ndimage as ndi
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb, load_mask
from simulate import radial_deform, colour_change, camera_matrix, apply_camera, photometric, random_camera
from register import METHODS

OUT = "/home/claude/melanotrack_ml/results/week5"
os.makedirs(OUT, exist_ok=True)


def make_followup(img, mask, rng, grow):
    if grow:
        f = float(rng.uniform(1.2, 1.6)); asym = float(rng.uniform(0.0, 0.6)); phi0 = float(rng.uniform(0, 2 * np.pi))
        g_img, g_mask = radial_deform(img, mask, f, asym, phi0)
        g_img = colour_change(g_img, g_mask, float(rng.uniform(0.3, 0.8)), rng)
    else:
        f, asym = 1.0, 0.0
        g_img, g_mask = img, mask
    cam = random_camera(rng)
    C = camera_matrix(cam["theta"], cam["scale"], cam["tx"], cam["ty"])
    fu_img, fu_mask = apply_camera(g_img, g_mask, C)
    fu_img = photometric(fu_img, rng)
    return fu_img, fu_mask, C, g_mask, dict(cam, area_factor=f, asym=asym)


def eval_points(mask_grown, ref_img, n=400, rng=None):
    """Skin points in the baseline frame that are unaffected by the lesion deformation."""
    far = ~ndi.binary_dilation(mask_grown > 0, iterations=25)
    fov = ref_img.max(axis=2) > 35
    far &= fov
    far[:12] = far[-12:] = False
    far[:, :12] = far[:, -12:] = False
    ys, xs = np.nonzero(far)
    if len(xs) < 20:  # lesion fills the view: fall back to all field-of-view pixels
        ys, xs = np.nonzero(fov)
    idx = rng.choice(len(xs), size=min(n, len(xs)), replace=False)
    return np.stack([xs[idx], ys[idx]], 1).astype(np.float64)


def run_one(args):
    i, img_path, mask_path, seed = args
    rng = np.random.default_rng(seed)
    ref = load_rgb(img_path); m_ref = load_mask(mask_path)
    rows = []
    for scen, grow in (("acquisition_only", False), ("acquisition_plus_growth", True)):
        fu, m_fu, C, m_grown, meta = make_followup(ref, m_ref, rng, grow)
        if m_fu.sum() < 30:
            continue
        P = eval_points(m_grown, ref, rng=rng)
        Q = (C[:, :2] @ P.T).T + C[:, 2]                     # where those skin points are in the follow-up
        true_ratio = m_grown.sum() / m_ref.sum()
        sel = os.environ.get("METHODS")
        for name, fn in METHODS.items():
            if sel and name not in sel.split(","):
                continue
            t0 = time.time()
            A, info = fn(ref, fu, m_ref, m_fu)
            dt = time.time() - t0
            Pe = (A[:, :2] @ Q.T).T + A[:, 2]
            err = np.linalg.norm(Pe - P, axis=1)
            wm = cv2.warpAffine(m_fu.astype(np.uint8), A, (256, 256), flags=cv2.INTER_NEAREST)
            inter = np.logical_and(wm > 0, m_ref > 0).sum(); uni = np.logical_or(wm > 0, m_ref > 0).sum()
            meas_ratio = wm.sum() / m_ref.sum()
            rows.append(dict(idx=i, scenario=scen, method=name, mean_err=float(err.mean()),
                             median_err=float(np.median(err)), iou=float(inter / max(uni, 1)),
                             true_growth=float(true_ratio - 1), measured_growth=float(meas_ratio - 1),
                             time_s=dt, fallback=bool(info.get("fallback", False)),
                             inliers=int(info.get("inliers", -1)), **{k: meta[k] for k in ("theta", "scale", "area_factor")}))
    return rows


if __name__ == "__main__":
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
    te = df[df.split == "test"].reset_index(drop=True)
    jobs = [(i, r.img, r["mask"], 1000 + i) for i, r in te.iterrows()]
    rows, t0 = [], time.time()
    with Pool(int(os.environ.get('PROCS', 2))) as pool:
        for k, rr in enumerate(pool.imap_unordered(run_one, jobs, chunksize=4)):
            rows.extend(rr)
            if k % 50 == 0:
                print(f"{k}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    out = pd.DataFrame(rows)
    suffix = os.environ.get("SUFFIX", "")
    if suffix:
        out.to_csv(f"{OUT}/registration_raw{suffix}.csv", index=False)
        sys.exit(0)
    out.to_csv(f"{OUT}/registration_raw.csv", index=False)
    summ = []
    for (scen, m), g in out.groupby(["scenario", "method"]):
        summ.append(dict(scenario=scen, method=m, n=len(g), median_err_px=g.median_err.median(),
                         mean_err_px=g.mean_err.mean(), success_2px=(g.mean_err < 2).mean(),
                         success_5px=(g.mean_err < 5).mean(), iou_mean=g.iou.mean(),
                         growth_abs_err_pp=(100 * (g.measured_growth - g.true_growth).abs()).mean(),
                         growth_retained=(g.measured_growth / g.true_growth.replace(0, np.nan)).median(),
                         fallback_rate=g.fallback.mean(), time_ms=1000 * g.time_s.mean()))
    s = pd.DataFrame(summ)
    s.to_csv(f"{OUT}/registration_summary.csv", index=False)
    print(s.to_string())
