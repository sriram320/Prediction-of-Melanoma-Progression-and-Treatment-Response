"""Week-7 figure: example lesion timeline (progressing and stable versions of the same real lesion)."""
import sys, os, json
import numpy as np
import pandas as pd
import cv2
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from register import reg_sift, warp_to_ref
from seg_classical import keep_central_component
from unet import UNet, predict_prob

OUT = "/home/claude/melanotrack_ml/results/week7"
SEQ = "/home/claude/melanotrack_ml/cache/seq"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7})
NAVY = "#1F3864"


def contour(ax, m, col, lw=1.0):
    if m.sum():
        ax.contour(m.astype(float), levels=[0.5], colors=[col], linewidths=lw)


def main():
    torch.set_num_threads(2)
    v = pd.read_csv(os.environ.get("SEQ_CSV", f"{SEQ}/visits.csv"))
    te = v[v.split == "test"]
    ok = te.groupby(["image_id", "version"]).agg(seg=("seg_dice", "min"), reg=("reg_ok", "all"), G=("G", "first"))
    ok = ok.reset_index()
    prog = ok[(ok.version == "prog") & ok.reg & (ok.seg > 0.9) & (ok.G > 1.6)]
    stab = ok[(ok.version == "stable") & ok.reg & (ok.seg > 0.9)]
    cand = sorted(set(prog.image_id) & set(stab.image_id))
    iid = os.environ.get("EX_ID", cand[len(cand) // 3] if cand else prog.image_id.iloc[0])
    model = UNet(pretrained=False)
    model.load_state_dict(torch.load("/home/claude/melanotrack_ml/cache/unet_r34.pt", map_location="cpu"))
    fig, axes = plt.subplots(3, 4, figsize=(6.6, 5.3))
    table = []
    for row, ver in ((0, "prog"), (2, "stable")):
        g = te[(te.image_id == iid) & (te.version == ver)].sort_values("t")
        imgs = [cv2.cvtColor(cv2.imread(f"{SEQ}/img/{iid}_{ver}_v{t}.jpg"), cv2.COLOR_BGR2RGB) for t in g.t]
        probs, _ = predict_prob(model, imgs)
        masks = [keep_central_component(p > 0.5) for p in probs]
        base, mb = imgs[0], masks[0]
        for k, (im, m, (_, r)) in enumerate(zip(imgs, masks, g.iterrows())):
            if ver == "prog":
                ax = axes[0, k]
                ax.imshow(im); contour(ax, m, "#FF3030")
                ax.set_title(f"Visit {k + 1}, month {r.month:.0f}\nas acquired", fontsize=6.4, color=NAVY)
                ax.axis("off")
            if k == 0:
                wi, wm = im, m
            else:
                A, info = reg_sift(base, im, mb, m, region="skin")
                _, wm = warp_to_ref(im, m, A, (256, 256))
                wi = cv2.warpAffine(im, A, (256, 256), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
            ax = axes[1 if ver == "prog" else 2, k]
            ax.imshow(wi); contour(ax, mb, "#00E5FF", 0.8); contour(ax, wm, "#FF3030", 0.9)
            ch = 100 * (r.f_area / g.f_area.iloc[0] - 1)
            ax.set_title(("Progressing" if ver == "prog" else "Stable") + f", registered\narea {ch:+.0f} % vs visit 1", fontsize=6.4, color=NAVY)
            ax.axis("off")
            table.append(dict(version=ver, visit=k + 1, month=float(r.month), area=float(r.f_area), area_change=float(ch),
                              max_diameter=float(r.f_max_diameter), asymmetry=float(r.f_asymmetry), compactness=float(r.f_compactness),
                              dE_skin=float(r.f_dE_skin), dL_skin=float(r.f_dL_skin), n_colours=int(r.f_n_colours),
                              colour_het=float(r.f_colour_heterogeneity), glcm_contrast=float(r.f_glcm_contrast),
                              true_area_change=float(100 * (r.true_area_px / g.true_area_px.iloc[0] - 1)), reg_ok=bool(r.reg_ok)))
    fig.tight_layout(h_pad=0.6, w_pad=0.3)
    fig.savefig(f"{OUT}/fig_example_timeline.png", dpi=220)
    plt.close(fig)
    json.dump(dict(image_id=iid, dx=te[te.image_id == iid].dx.iloc[0], G=float(ok[(ok.image_id == iid) & (ok.version == "prog")].G.iloc[0]),
                   rows=table), open(f"{OUT}/example.json", "w"), indent=2)
    print(iid, pd.DataFrame(table).round(3).to_string())


if __name__ == "__main__":
    main()
