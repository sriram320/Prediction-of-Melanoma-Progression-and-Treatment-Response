"""Week-5 segmentation evaluation on the held-out ISIC 2017 test split (430 images with expert masks)."""
import sys, os, json, time
import numpy as np
import pandas as pd
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb, load_mask
from seg_classical import otsu_segment, grabcut_segment, user_box_from_mask, dice_iou, boundary_hd95, keep_central_component
from unet import UNet, predict_prob, tta_confidence

torch.set_num_threads(2)
OUT = "/home/claude/melanotrack_ml/results/week5"


def postprocess(prob):
    return keep_central_component(prob > 0.5)


if __name__ == "__main__":
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
    te = df[df.split == "test"].reset_index(drop=True)
    model = UNet(pretrained=False)
    model.load_state_dict(torch.load("/home/claude/melanotrack_ml/cache/unet_r34.pt", map_location="cpu"))
    model.eval()
    rng = np.random.default_rng(7)
    rows, preds = [], {}
    t_unet = t_tta = t_otsu = t_gc = 0.0
    for b in range(0, len(te), 16):
        chunk = te.iloc[b:b + 16]
        imgs = [load_rgb(p) for p in chunk.img]
        gts = [load_mask(m) for m in chunk["mask"]]
        t0 = time.time(); p1, _ = predict_prob(model, imgs, tta=False); t_unet += time.time() - t0
        t0 = time.time(); p8, maps = predict_prob(model, imgs, tta=True); t_tta += time.time() - t0
        conf = tta_confidence(p8, maps)
        for k, (img, gt) in enumerate(zip(imgs, gts)):
            iid = chunk.image_id.iloc[k]
            t0 = time.time(); m_otsu = otsu_segment(img); t_otsu += time.time() - t0
            box = user_box_from_mask(gt, rng=rng)
            t0 = time.time(); m_gc = grabcut_segment(img, rect=box); t_gc += time.time() - t0
            m_gca = grabcut_segment(img, init_mask=m_otsu) if m_otsu.sum() > 0 else m_otsu
            m_u = postprocess(p1[k]); m_ut = postprocess(p8[k])
            preds[iid] = dict(otsu=m_otsu, grabcut_box=m_gc, unet=m_u, unet_tta=m_ut, box=box)
            for name, m in (("Otsu (automatic)", m_otsu), ("Otsu + GrabCut (automatic)", m_gca),
                            ("GrabCut from user box (semi-automatic)", m_gc), ("U-Net (automatic)", m_u),
                            ("U-Net + 8-way TTA (automatic)", m_ut)):
                d, j = dice_iou(m, gt)
                tp = np.logical_and(m > 0, gt > 0).sum(); fn = np.logical_and(m == 0, gt > 0).sum()
                tn = np.logical_and(m == 0, gt == 0).sum(); fp = np.logical_and(m > 0, gt == 0).sum()
                rows.append(dict(image_id=iid, dx=chunk.dx.iloc[k], method=name, dice=d, iou=j,
                                 thr_jaccard=j if j >= 0.65 else 0.0, hd95=boundary_hd95(m, gt),
                                 sensitivity=tp / max(1, tp + fn), specificity=tn / max(1, tn + fp),
                                 tta_conf=conf[k] if "U-Net" in name else np.nan))
        print(b, flush=True)
    r = pd.DataFrame(rows)
    r.to_csv(f"{OUT}/segmentation_raw.csv", index=False)
    summ = r.groupby("method").agg(dice_mean=("dice", "mean"), dice_median=("dice", "median"), iou_mean=("iou", "mean"),
                                   thr_jaccard=("thr_jaccard", "mean"), hd95_median=("hd95", "median"),
                                   sensitivity=("sensitivity", "mean"), specificity=("specificity", "mean"),
                                   fail_rate=("iou", lambda x: (x < 0.65).mean())).reset_index()
    n = len(te)
    summ["sec_per_image"] = summ.method.map({"Otsu (automatic)": t_otsu / n, "GrabCut from user box (semi-automatic)": t_gc / n,
                                             "U-Net (automatic)": t_unet / n, "U-Net + 8-way TTA (automatic)": t_tta / n})
    summ.to_csv(f"{OUT}/segmentation_summary.csv", index=False)
    bydx = r.pivot_table(index="method", columns="dx", values="dice", aggfunc="mean")
    bydx.to_csv(f"{OUT}/segmentation_by_dx.csv")
    # does the TTA confidence flag bad masks?
    from scipy.stats import spearmanr
    from sklearn.metrics import roc_auc_score
    u = r[r.method == "U-Net + 8-way TTA (automatic)"]
    bad = (u.iou < 0.8).astype(int)
    conf_stats = dict(spearman_conf_iou=float(spearmanr(u.tta_conf, u.iou).correlation),
                      auroc_conf_flags_iou_below_0_8=float(roc_auc_score(bad, -u.tta_conf)) if bad.nunique() > 1 else None,
                      n_iou_below_0_8=int(bad.sum()),
                      flagged_at_0_85=int((u.tta_conf < 0.85).sum()),
                      mean_iou_flagged=float(u.iou[u.tta_conf < 0.85].mean()) if (u.tta_conf < 0.85).any() else None,
                      mean_iou_not_flagged=float(u.iou[u.tta_conf >= 0.85].mean()))
    json.dump(conf_stats, open(f"{OUT}/segmentation_confidence.json", "w"), indent=2)
    np.savez_compressed(f"{OUT}/seg_preds.npz", **{f"{k}__{m}": v[m] for k, v in preds.items() for m in ("otsu", "grabcut_box", "unet_tta")})
    json.dump({k: [int(x) for x in v["box"]] for k, v in preds.items()}, open(f"{OUT}/seg_boxes.json", "w"))
    print(summ.to_string()); print(bydx.round(3).to_string()); print(conf_stats)
