"""Week-9 figures: baseline comparison, ROC curves, sensitivity analysis, attention over visits."""
import os, json, pickle
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, roc_auc_score

R = "/home/claude/melanotrack_ml/results/week9"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
NAVY, BLUE, LIGHT, PINK, GREY = "#1F3864", "#2E75B6", "#9DC3E6", "#C0504D", "#7F7F7F"
LAB = {"image_last": "Image only (last visit)", "change_only": "Change features only", "early_fusion": "Early fusion (LR)",
       "late_fusion": "Late fusion (stacked)", "gru_attn": "GRU + attention", "transformer": "Transformer encoder",
       "gru_noimg": "GRU, no image features"}


def baselines():
    b = pd.read_csv(f"{R}/baselines.csv")
    b = b.iloc[::-1]
    fig, ax = plt.subplots(figsize=(5.6, 2.1))
    ys = np.arange(len(b))
    cols = [PINK if "fusion" in m else (BLUE if "Transformer" in m else (GREY if "Handcrafted" in m else LIGHT)) for m in b.model]
    ax.barh(ys, b.auroc, color=cols, height=0.6)
    ax.errorbar(b.auroc, ys, xerr=[b.auroc - b.auroc_lo, b.auroc_hi - b.auroc], fmt="none", ecolor="k", elinewidth=0.7, capsize=2)
    for y, a, c in zip(ys, b.auroc, cols):
        ax.text(0.505, y, f"{a:.3f}", va="center", fontsize=6.5, color="k" if c == LIGHT else "white")
    ax.set_yticks(ys); ax.set_yticklabels(b.model, fontsize=6.6)
    ax.set_xlim(0.5, 1.0); ax.set_xlabel("Test AUROC, melanoma vs benign (95 % bootstrap CI)")
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="x", alpha=0.3, lw=0.5)
    fig.tight_layout(); fig.savefig(f"{R}/fig_baselines.png", dpi=220); plt.close(fig)


def rocs():
    pr = pickle.load(open(f"{R}/temporal_preds.pkl", "rb"))
    lab = pr["labels"]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9))
    for ax, ep, ttl in zip(axes, ("endpointA", "endpointB"), ("Endpoint A: progressed (melanoma or documented change)", "Endpoint B: melanoma")):
        y = lab[ep].values
        for m, c, ls in (("image_last", GREY, "--"), ("change_only", LIGHT, "-"), ("early_fusion", BLUE, "-"), ("gru_attn", PINK, "-")):
            s = pr[f"{ep}__{m}"]
            fpr, tpr, _ = roc_curve(y, s)
            ax.plot(fpr, tpr, ls, color=c, lw=1.3, label=f"{LAB[m]} ({roc_auc_score(y, s):.3f})")
        ax.plot([0, 1], [0, 1], ":", color="k", lw=0.6)
        ax.set_title(ttl, fontsize=7.2, color=NAVY)
        ax.set_xlabel("1 - specificity"); ax.set_ylabel("Sensitivity")
        ax.legend(frameon=False, fontsize=6.0, loc="lower right")
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(f"{R}/fig_roc.png", dpi=220); plt.close(fig)


def sensitivity():
    m = pd.read_csv(f"{R}/temporal_main.csv"); s = pd.read_csv(f"{R}/temporal_sensitivity.csv")
    d = pd.concat([m, s])
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.6))
    for ax, ep, ttl in zip(axes, ("endpointA", "endpointB"), ("Endpoint A: progressed", "Endpoint B: melanoma")):
        dd = d[(d.endpoint == ep) & (d.p_mel == 0.7)]
        for mname, c in (("image_last", GREY), ("change_only", LIGHT), ("early_fusion", BLUE), ("gru_attn", PINK)):
            x = dd[dd.model == mname].sort_values("p_ben")
            ax.plot(x.p_ben, x.auroc, "-o", color=c, ms=3, lw=1.3, label=LAB[mname])
        ctrl = d[(d.endpoint == ep) & (d.p_mel == 0.4) & (d.p_ben == 0.4)]
        for mname, c in (("change_only", LIGHT), ("early_fusion", BLUE), ("gru_attn", PINK)):
            v = ctrl[ctrl.model == mname].auroc
            if len(v):
                ax.scatter([0.62], v, marker="s", color=c, s=14, zorder=3)
        ax.axvline(0.585, color="k", lw=0.5, ls=":")
        ax.text(0.62, 0.975, "control\n(no link)", fontsize=5.8, ha="center", va="top")
        ax.set_xticks([0.1, 0.25, 0.4, 0.55, 0.62]); ax.set_xticklabels(["0.10", "0.25", "0.40", "0.55", "ctrl"])
        ax.set_xlabel("P(change | benign lesion); P(change | melanoma) = 0.7")
        ax.set_ylabel("Test AUROC"); ax.set_ylim(0.45, 1.0)
        ax.set_title(ttl, fontsize=7.4, color=NAVY)
        ax.spines[["top", "right"]].set_visible(False); ax.grid(alpha=0.25, lw=0.5)
    axes[1].legend(frameon=False, fontsize=6.0, loc="lower left")
    fig.tight_layout(); fig.savefig(f"{R}/fig_sensitivity.png", dpi=220); plt.close(fig)


def attention():
    pr = pickle.load(open(f"{R}/temporal_preds.pkl", "rb"))
    att, lab = pr["endpointA__attention"].values, pr["labels"]
    fig, ax = plt.subplots(figsize=(3.4, 2.0))
    xs = np.arange(att.shape[1])
    for k, (g, c, name) in enumerate(((1, PINK, "Progressing"), (0, BLUE, "Stable"))):
        a = att[lab.progress.values == g].mean(0)
        ax.bar(xs + (k - 0.5) * 0.38, a, 0.38, color=c, label=name)
    ax.set_xticks(xs); ax.set_xticklabels([f"Visit {i + 1}" for i in xs])
    ax.set_ylabel("Mean attention weight"); ax.legend(frameon=False, fontsize=6.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(f"{R}/fig_attention.png", dpi=220); plt.close(fig)
    out = {"attention_prog": att[lab.progress.values == 1].mean(0).tolist(), "attention_stable": att[lab.progress.values == 0].mean(0).tolist()}
    return out


if __name__ == "__main__":
    extra = {}
    if os.path.exists(f"{R}/baselines.csv"):
        baselines()
    if os.path.exists(f"{R}/temporal_preds.pkl"):
        rocs(); extra.update(attention())
    if os.path.exists(f"{R}/temporal_sensitivity.csv"):
        sensitivity()
    json.dump(extra, open(f"{R}/extra.json", "w"), indent=2)
    print(extra)
