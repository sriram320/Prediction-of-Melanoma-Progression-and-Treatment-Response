"""Week-5 figures: segmentation overlays, Dice distributions, registration before/after comparisons."""
import sys, os, json
import numpy as np
import pandas as pd
import cv2
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from skimage import color
from scipy import ndimage as ndi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb, load_mask
from simulate import radial_deform, colour_change, camera_matrix, apply_camera, photometric, random_camera
from register import reg_sift, warp_to_ref
from seg_classical import keep_central_component, dice_iou
from unet import UNet, predict_prob

OUT = "/home/claude/melanotrack_ml/results/week5"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
NAVY = "#1F3864"


def contour(ax, m, col, lw=1.1, ls="-"):
    if m.sum() == 0:
        return
    ax.contour(m.astype(float), levels=[0.5], colors=[col], linewidths=lw, linestyles=ls)


def seg_examples(model):
    r = pd.read_csv(f"{OUT}/segmentation_raw.csv")
    u = r[r.method == "U-Net + 8-way TTA (automatic)"].set_index("image_id")
    o = r[r.method == "Otsu (automatic)"].set_index("image_id")
    g = r[r.method == "GrabCut from user box (semi-automatic)"].set_index("image_id")
    preds = np.load(f"{OUT}/seg_preds.npz")
    boxes = json.load(open(f"{OUT}/seg_boxes.json"))
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv").set_index("image_id")
    # pick: 5 typical (near median U-Net dice, varied dx), 1 hard case for Otsu, 2 lowest U-Net
    q = u.dice.sort_values()
    picks = list(q.index[[len(q) // 2 - 40, len(q) // 2, len(q) // 2 + 40, int(len(q) * 0.85)]])
    otsu_bad = (u.dice - o.dice).sort_values(ascending=False).index[:12]
    picks += [i for i in otsu_bad if i not in picks][:2]
    picks += list(q.index[:2])
    fig, axes = plt.subplots(2, 4, figsize=(7.0, 3.75))
    for ax, iid in zip(axes.ravel(), picks):
        img = load_rgb(df.loc[iid, "img"]); gt = load_mask(df.loc[iid, "mask"])
        ax.imshow(img)
        contour(ax, gt, "#00D000", 1.6)
        contour(ax, preds[f"{iid}__otsu"], "#FFD700", 0.9)
        contour(ax, preds[f"{iid}__grabcut_box"], "#00E5FF", 0.9)
        contour(ax, preds[f"{iid}__unet_tta"], "#FF3030", 1.1)
        x, y_, w, h = boxes[iid]
        ax.add_patch(plt.Rectangle((x, y_), w, h, fill=False, ec="#00E5FF", lw=0.6, ls="--"))
        ax.set_title(df.loc[iid, "dx"].replace("_", " ").replace("seb", "seborrhoeic"), fontsize=6.6)
        for k, (val, col) in enumerate(((u.loc[iid, "dice"], "#FF3030"), (g.loc[iid, "dice"], "#00E5FF"), (o.loc[iid, "dice"], "#FFD700"))):
            ax.text(6, 18 + k * 21, f"{val:.2f}", color=col, fontsize=6.4, weight="bold",
                    bbox=dict(fc="black", ec="none", alpha=0.55, pad=1.0))
        ax.axis("off")
    handles = [Line2D([0], [0], color=c, lw=1.6) for c in ("#00D000", "#FF3030", "#00E5FF", "#FFD700")]
    fig.legend(handles, ["Expert mask", "U-Net + TTA (automatic)", "GrabCut from box (semi-automatic)", "Otsu (automatic)"],
               loc="lower center", ncol=4, frameon=False, fontsize=7)
    fig.patch.set_facecolor("white")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(f"{OUT}/fig_seg_examples.png", dpi=220)
    plt.close(fig)


def dice_box():
    r = pd.read_csv(f"{OUT}/segmentation_raw.csv")
    order = ["Otsu (automatic)", "Otsu + GrabCut (automatic)", "GrabCut from user box (semi-automatic)",
             "U-Net (automatic)", "U-Net + 8-way TTA (automatic)"]
    labels = ["Otsu", "Otsu +\nGrabCut", "GrabCut\n(user box)", "U-Net", "U-Net +\nTTA"]
    data = [r[r.method == m].dice.values for m in order]
    fig, ax = plt.subplots(figsize=(4.6, 2.3))
    bp = ax.boxplot(data, tick_labels=labels, showfliers=True, widths=0.55, patch_artist=True,
                    flierprops=dict(marker=".", ms=2, alpha=0.4), medianprops=dict(color="black"))
    for patch, c in zip(bp["boxes"], ["#F2F2F2", "#F2F2F2", "#DCE6F1", "#2E75B6", "#2E75B6"]):
        patch.set_facecolor(c)
    ax.set_ylabel("Dice (430 test images)")
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", alpha=0.3, lw=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_seg_dice.png", dpi=220)
    plt.close(fig)


def segment(model, img):
    p, _ = predict_prob(model, [img])
    return keep_central_component(p[0] > 0.5)


def checker(a, b, n=8):
    h, w = a.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    sel = ((yy // (h // n)) + (xx // (w // n))) % 2 == 0
    out = b.copy()
    out[sel] = a[sel]
    return out


def registration_panel(model, iid, seed, fname, growth=1.45, asym=0.6):
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv").set_index("image_id")
    rng = np.random.default_rng(seed)
    ref = load_rgb(df.loc[iid, "img"]); m_gt = load_mask(df.loc[iid, "mask"])
    g_img, g_mask = radial_deform(ref, m_gt, growth, asym, rng.uniform(0, 2 * np.pi))
    g_img = colour_change(g_img, g_mask, 0.7, rng)
    C = camera_matrix(22.0, 1.10, 12.0, -9.0)
    fu, fu_true = apply_camera(g_img, g_mask, C)
    fu = photometric(fu, rng)
    m_ref = segment(model, ref); m_fu = segment(model, fu)
    A, info = reg_sift(ref, fu, m_ref, m_fu, region="skin")
    info["stage"] = f"SIFT on skin, {info.get('inliers', 0)} inliers" if info.get("ok") else "flagged: mask-moment fallback"
    fu_w, m_fu_w = warp_to_ref(fu, m_fu, A, (256, 256))
    lab_r = color.rgb2lab(ref / 255.0); lab_w = color.rgb2lab(fu_w / 255.0)
    dE = color.deltaE_ciede2000(lab_r, lab_w)
    roi = ndi.binary_dilation((m_ref > 0) | (m_fu_w > 0), iterations=5)
    dE_disp = np.where(roi & (dE > 10), dE, np.nan)
    grown = (m_fu_w > 0) & (m_ref == 0); lost = (m_ref > 0) & (m_fu_w == 0); kept = (m_ref > 0) & (m_fu_w > 0)
    change = np.ones((256, 256, 3)) * 0.92
    change[kept] = (0.75, 0.75, 0.75); change[grown] = (0.85, 0.15, 0.15); change[lost] = (0.15, 0.35, 0.85)
    area_change = 100 * (m_fu_w.sum() / m_ref.sum() - 1)
    true_change = 100 * (g_mask.sum() / m_gt.sum() - 1)
    fig, axes = plt.subplots(2, 4, figsize=(7.0, 3.85))
    panels = [(ref, "(a) Baseline visit"), (fu, "(b) Follow-up as acquired"), (fu_w, f"(c) Follow-up registered\n({info.get('stage', '')})"),
              (checker(ref, fu), "(d) Checkerboard before"), (checker(ref, fu_w), "(e) Checkerboard after"), (ref, "(f) Contours after alignment"),
              (None, "(g) Colour difference ΔE2000 > 10"), (change, f"(h) Change map: {area_change:+.0f} % (true {true_change:+.0f} %)")]
    for ax, (im, t) in zip(axes.ravel(), panels):
        if im is not None:
            ax.imshow(im)
        ax.set_title(t, fontsize=6.6, color=NAVY)
        ax.axis("off")
    contour(axes[0, 0], m_ref, "#00E5FF"); contour(axes[0, 1], m_fu, "#FF3030")
    contour(axes[0, 3], m_ref, "#00E5FF", 0.8); contour(axes[0, 3], m_fu, "#FF3030", 0.8)
    contour(axes[1, 0], m_ref, "#00E5FF", 0.8); contour(axes[1, 0], m_fu_w, "#FF3030", 0.8)
    contour(axes[1, 1], m_ref, "#00E5FF", 0.8); contour(axes[1, 1], m_fu_w, "#FF3030", 0.8)
    axes[1, 2].imshow(ref); axes[1, 2].imshow(dE_disp, cmap="magma", alpha=0.85, vmin=10, vmax=45)
    contour(axes[1, 2], m_ref, "#00E5FF", 0.7)
    fig.tight_layout(h_pad=1.2)
    fig.savefig(f"{OUT}/{fname}", dpi=220)
    plt.close(fig)
    return dict(image_id=iid, stage=info.get("stage"), measured_area_change=area_change, true_area_change=true_change,
                inliers=info.get("inliers"))


def reg_chart():
    s = pd.read_csv(f"{OUT}/registration_summary_all.csv")
    order = ["none", "moments_scale", "moments_rigid", "ecc_affine", "sift_whole_v2", "ecc_skin", "sift_skin", "sift_skin_v2"]
    lab = {"none": "None", "moments_scale": "Moments\n+ scale", "moments_rigid": "Moments\nrigid",
           "ecc_affine": "ECC\nwhole", "sift_whole_v2": "SIFT\nwhole", "ecc_skin": "ECC\nskin",
           "sift_skin": "SIFT\nskin v1", "sift_skin_v2": "SIFT\nskin v2*"}
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.5))
    for ax, (col, ttl, fmt) in zip(axes, (("success_2px", "Alignment success (error < 2 px)", "{:.0%}"),
                                          ("growth_abs_err_pp", "Error in measured growth (pp)", "{:.1f}"))):
        for k, (scen, c) in enumerate((("acquisition_only", "#9DC3E6"), ("acquisition_plus_growth", "#2E75B6"))):
            d = s[s.scenario == scen].set_index("method").reindex(order)
            vals = d[col].values
            if col == "growth_abs_err_pp" and scen == "acquisition_only":
                continue
            xs = np.arange(len(order)) + (k - 0.5) * 0.38 * (col != "growth_abs_err_pp")
            ax.bar(xs, vals, 0.38 if col != "growth_abs_err_pp" else 0.6, color=c,
                   label="Acquisition change only" if k == 0 else "Acquisition change + lesion growth")
        ax.set_xticks(np.arange(len(order)))
        ax.set_xticklabels([lab[o] for o in order], fontsize=6.0)
        ax.set_title(ttl, fontsize=7.5, color=NAVY)
        ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=0.3, lw=0.5)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=6.6)
    axes[0].set_ylim(0, 1.05)
    fig.text(0.99, 0.005, "* proposed", ha="right", fontsize=6)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(f"{OUT}/fig_reg_chart.png", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    torch.set_num_threads(2)
    model = UNet(pretrained=False)
    model.load_state_dict(torch.load("/home/claude/melanotrack_ml/cache/unet_r34.pt", map_location="cpu"))
    model.eval()
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "seg"):
        seg_examples(model); dice_box()
    if what in ("all", "reg"):
        reg_chart()
        df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv")
        te = df[df.split == "test"]
        ex = []
        for iid, seed, fn in ((os.environ.get("REG_ID1", te.image_id.iloc[3]), 11, "fig_reg_example1.png"),
                              (os.environ.get("REG_ID2", te.image_id.iloc[17]), 12, "fig_reg_example2.png")):
            ex.append(registration_panel(model, iid, seed, fn))
        json.dump(ex, open(f"{OUT}/reg_examples.json", "w"), indent=2, default=float)
        print(ex)
