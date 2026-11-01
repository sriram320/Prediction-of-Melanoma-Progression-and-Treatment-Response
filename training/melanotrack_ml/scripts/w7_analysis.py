"""Week-7: temporal feature extraction and lesion change analysis on the simulated visit sequences.

Uses cache/seq/visits.csv (built by build_sequences.py). Test-split lesions only; each lesion has a
'progressing' and a 'stable' version, so the two groups contain the same 430 real lesions.
Outputs tables (CSV/JSON) and figures to results/week7.
"""
import sys, os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from features import FEATURE_GROUPS

OUT = "/home/claude/melanotrack_ml/results/week7"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8})
BLUE, GREY, PINK, NAVY = "#2E75B6", "#7F7F7F", "#C0504D", "#1F3864"

SIZE = ["area", "eq_diameter", "max_diameter", "perimeter"]
KEY = {
    "area": "Area", "max_diameter": "Max. diameter", "asymmetry": "Asymmetry index", "compactness": "Border compactness",
    "radial_cv": "Radial irregularity", "solidity": "Solidity", "dE_skin": "Lesion-skin colour contrast (dE)",
    "dL_skin": "Lightness vs skin (dL*)", "colour_heterogeneity": "Colour heterogeneity", "n_colours": "No. of colours",
    "glcm_contrast": "GLCM contrast", "lbp_entropy": "LBP entropy",
}


def per_lesion_change(v, prefix):
    """Change from first to last visit; size features as relative change (%), others as absolute."""
    rows = []
    for (iid, ver), g in v.groupby(["image_id", "version"]):
        g = g.sort_values("t")
        if g[f"{prefix}area"].isna().any():
            continue
        r = dict(image_id=iid, version=ver, progress=g.progress.iloc[0], dx=g.dx.iloc[0], G=g.G.iloc[0],
                 all_reg_ok=bool(g.reg_ok.astype(bool).all()),
                 true_area_change=100 * (g.true_area_px.iloc[-1] / g.true_area_px.iloc[0] - 1))
        m = g.month.values
        for f in FEATURE_GROUPS_FLAT:
            x = g[f"{prefix}{f}"].values.astype(float)
            if f in SIZE:
                rel = 100 * (x / x[0] - 1)
                r[f] = rel[-1]
                r[f + "_slope"] = np.polyfit(m, rel, 1)[0]
            else:
                r[f] = x[-1] - x[0]
                r[f + "_slope"] = np.polyfit(m, x, 1)[0]
        rows.append(r)
    return pd.DataFrame(rows)


FEATURE_GROUPS_FLAT = [f for g in FEATURE_GROUPS.values() for f in g]


def main():
    v = pd.read_csv(os.environ.get("SEQ_CSV", "/home/claude/melanotrack_ml/cache/seq/visits.csv"))
    te = v[v.split == "test"].copy()
    summary = {}
    # ---------------- pipeline quality on the sequences
    summary["n_lesions"] = int(te.image_id.nunique())
    summary["n_visits"] = int(len(te))
    summary["seg_dice_mean"] = float(te.seg_dice.mean())
    fu = te[te.t > 0]
    summary["reg_err_median_px"] = float(fu.reg_err.median())
    summary["reg_success_2px"] = float((fu.reg_err < 2).mean())
    summary["reg_success_5px"] = float((fu.reg_err < 5).mean())
    summary["reg_fallback_rate"] = float(fu.reg_fallback.mean())
    pipe = per_lesion_change(te, "f_")
    orac = per_lesion_change(te, "o_")
    pipe.to_csv(f"{OUT}/lesion_changes_pipeline.csv", index=False)
    orac.to_csv(f"{OUT}/lesion_changes_oracle.csv", index=False)

    # ---------------- 1) accuracy of area change against the known truth
    acc = {}
    summary["accepted_fraction"] = float(pipe.all_reg_ok.mean())
    summary["accepted_fraction_progressing"] = float(pipe[pipe.progress == 1].all_reg_ok.mean())
    summary["accepted_fraction_stable"] = float(pipe[pipe.progress == 0].all_reg_ok.mean())
    pipe_acc = pipe[pipe.all_reg_ok]
    for name, d in (("pipeline", pipe), ("pipeline_accepted", pipe_acc), ("oracle", orac)):
        err = d.area - d.true_area_change
        acc[name] = dict(mae_pp=float(err.abs().mean()), medae_pp=float(err.abs().median()), bias_pp=float(err.mean()), sd_pp=float(err.std()),
                         r=float(np.corrcoef(d.area, d.true_area_change)[0, 1]),
                         loa_low=float(err.mean() - 1.96 * err.std()), loa_high=float(err.mean() + 1.96 * err.std()))
    summary["area_change_accuracy"] = acc
    for t_ in (0, 3):
        summary[f"oracle_compactness_prog_v{t_ + 1}"] = float(te[(te.version == "prog") & (te.t == t_)].o_compactness.mean())
        summary[f"pipeline_compactness_prog_v{t_ + 1}"] = float(te[(te.version == "prog") & (te.t == t_)].f_compactness.mean())
    pr_all = orac[orac.progress == 1].true_area_change
    summary["prog_true_change_min"], summary["prog_true_change_max"] = float(pr_all.min()), float(pr_all.max())
    summary["prog_true_change_mean"] = float(pr_all.mean())
    fl = pipe[~pipe.all_reg_ok]
    summary["flagged_mae_pp"] = float((fl.area - fl.true_area_change).abs().mean()) if len(fl) else None
    pa_prog = pipe_acc[pipe_acc.progress == 1]
    summary["accepted_prog_bias_pp"] = float((pa_prog.area - pa_prog.true_area_change).mean())
    summary["accepted_prog_mae_pp"] = float((pa_prog.area - pa_prog.true_area_change).abs().mean())
    summary["accepted_prog_true_mean"] = float(pa_prog.true_area_change.mean())
    summary["accepted_prog_meas_mean"] = float(pa_prog.area.mean())
    summary["accepted_stable_mae_pp"] = float((pipe_acc[pipe_acc.progress == 0].area - pipe_acc[pipe_acc.progress == 0].true_area_change).abs().mean())

    # ---------------- 1b) where the area-change error comes from (native areas and registration scales)
    ok_keys = set(zip(pipe_acc.image_id, pipe_acc.version))
    dec = []
    for (iid, ver), g in te.groupby(["image_id", "version"]):
        g = g.sort_values("t")
        b, l = g.iloc[0], g.iloc[-1]
        if b.pred_area_raw < 30 or l.pred_area_raw < 30:
            continue
        tr = 100 * (l.true_area_px / b.true_area_px - 1)
        dec.append(dict(image_id=iid, version=ver, accepted=(iid, ver) in ok_keys, true=tr,
                        oracle=100 * (l.true_scale ** 2 * l.true_area_native / b.true_area_native - 1),
                        seg_only=100 * (l.true_scale ** 2 * l.pred_area_raw / b.pred_area_raw - 1),
                        reg_only=100 * (l.reg_scale ** 2 * l.true_area_native / b.true_area_native - 1),
                        pipeline=100 * (l.reg_scale ** 2 * l.pred_area_raw / b.pred_area_raw - 1)))
    dec = pd.DataFrame(dec)
    dec.to_csv(f"{OUT}/error_decomposition.csv", index=False)
    da = dec[dec.accepted]
    summary["error_decomposition_accepted"] = {m: dict(mae_pp=float((da[m] - da.true).abs().mean()),
                                                       bias_prog_pp=float((da[m] - da.true)[da.version == "prog"].mean()),
                                                       sd_stable_pp=float(da[da.version == "stable"][m].std()))
                                               for m in ("oracle", "seg_only", "reg_only", "pipeline")}
    # per-visit segmentation area error (U-Net vs truth, own frame)
    rel = 100 * (te.pred_area_raw / te.true_area_native - 1)
    summary["seg_area_err_visit_sd_pct"] = float(rel.std())
    summary["seg_area_err_visit_mean_pct"] = float(rel.mean())
    gross = rel > 100                                    # U-Net mask more than twice the true area
    first_prog = (te.version == "prog") & (te.t == 0)
    summary["gross_overseg_prog_first"] = float(gross[first_prog].mean())
    summary["gross_overseg_other"] = float(gross[~first_prog].mean())
    summary["seg_area_abs_err_median_pct"] = float(rel.abs().median())
    summary["seg_area_err_median_pct"] = float(rel.median())
    for ver in ("prog", "stable"):
        for t in (0, 3):
            summary[f"seg_area_err_mean_{ver}_v{t}"] = float(rel[(te.version == ver) & (te.t == t)].mean())

    # ---------------- 2) noise floor on stable lesions and discrimination progressing vs stable
    rows = []
    for grp, feats in FEATURE_GROUPS.items():
        for f in feats:
            st_p = pipe[pipe.progress == 0][f]
            st_o = orac[orac.progress == 0][f]
            pr_p = pipe[pipe.progress == 1][f]
            auc = roc_auc_score(pipe.progress, pipe[f])
            auc_acc = roc_auc_score(pipe_acc.progress, pipe_acc[f])
            pooled = np.sqrt((st_p.var() + pr_p.var()) / 2)
            rows.append(dict(group=grp, feature=f, unit="%" if f in SIZE else "abs",
                             stable_sd_pipeline=st_p.std(), stable_sd_oracle=st_o.std(),
                             stable_mean_pipeline=st_p.mean(), progressing_mean_pipeline=pr_p.mean(),
                             cohen_d=(pr_p.mean() - st_p.mean()) / pooled if pooled > 0 else np.nan,
                             auroc=max(auc, 1 - auc), direction="+" if auc >= 0.5 else "-",
                             auroc_accepted=max(auc_acc, 1 - auc_acc),
                             stable_sd_accepted=pipe_acc[pipe_acc.progress == 0][f].std(),
                             auroc_oracle=max(roc_auc_score(orac.progress, orac[f]), 1 - roc_auc_score(orac.progress, orac[f]))))
    tab = pd.DataFrame(rows)
    tab.to_csv(f"{OUT}/feature_change_table.csv", index=False)

    # minimum detectable change for area (95 % one-sided on stable lesions)
    summary["area_mdc95_pipeline_pp"] = float(1.645 * pipe[pipe.progress == 0].area.std())
    summary["area_mdc95_accepted_pp"] = float(1.645 * pipe_acc[pipe_acc.progress == 0].area.std())
    thr_a = summary["area_mdc95_accepted_pp"]
    summary["detected_growth_rate_accepted"] = float((pipe_acc[pipe_acc.progress == 1].area > thr_a).mean())
    summary["false_growth_rate_accepted"] = float((pipe_acc[pipe_acc.progress == 0].area > thr_a).mean())
    summary["area_mdc95_oracle_pp"] = float(1.645 * orac[orac.progress == 0].area.std())
    thr = summary["area_mdc95_pipeline_pp"]
    summary["detected_growth_rate_pipeline"] = float((pipe[pipe.progress == 1].area > thr).mean())
    summary["false_growth_rate_pipeline"] = float((pipe[pipe.progress == 0].area > thr).mean())

    # ---------------- 3) trajectories (figure)
    feats6 = [("area", "Size: area change (%)"), ("max_diameter", "Size: max. diameter change (%)"),
              ("asymmetry", "Asymmetry index"), ("compactness", "Border: compactness (P²/4πA)"),
              ("solidity", "Shape: solidity"), ("dE_skin", "Colour: lesion-skin contrast ΔE"),
              ("colour_heterogeneity", "Colour: heterogeneity (ΔE)"), ("glcm_energy", "Texture: GLCM energy")]
    fig, axes = plt.subplots(2, 4, figsize=(7.6, 3.9))
    traj_rows = []
    for ax, (f, lab) in zip(axes.ravel(), feats6):
        ok_keys = set(zip(pipe_acc.image_id, pipe_acc.version))
        for prog, col, name in ((1, PINK, "Progressing"), (0, BLUE, "Stable")):
            keep = np.array([k in ok_keys for k in zip(te.image_id, te.version)])
            g = te[(te.progress.values == prog) & keep]
            ys = []
            for (iid, ver), gg in g.groupby(["image_id", "version"]):
                gg = gg.sort_values("t")
                x = gg[f"f_{f}"].values.astype(float)
                ys.append(100 * (x / x[0] - 1) if f in SIZE else x)
            ys = np.array(ys)
            mon = g.groupby("t").month.mean().values
            mu, sd = np.nanmean(ys, 0), np.nanstd(ys, 0)
            ci = 1.96 * sd / np.sqrt(len(ys))
            ax.plot(mon, mu, "-o", color=col, ms=3, lw=1.4, label=name)
            ax.fill_between(mon, mu - sd, mu + sd, color=col, alpha=0.12, lw=0)
            for t in range(len(mon)):
                traj_rows.append(dict(feature=f, group=name, visit=t, month=mon[t], mean=mu[t], sd=sd[t], ci95=ci[t]))
        ax.set_title(lab, fontsize=7.0, color=NAVY)
        ax.set_xticks([0, 6, 12, 18]); ax.grid(alpha=0.25, lw=0.5)
        ax.spines[["top", "right"]].set_visible(False)
    for ax in axes[1]:
        ax.set_xlabel("Months since baseline")
    axes[0, 0].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_trajectories.png", dpi=220)
    plt.close(fig)
    pd.DataFrame(traj_rows).to_csv(f"{OUT}/trajectories.csv", index=False)

    # ---------------- 4) measured vs true area change (figure)
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.7), sharey=True)
    for ax, (name, d) in zip(axes, (("Oracle masks and transforms", orac), ("Full pipeline, registration accepted", pipe_acc))):
        c = np.where(d.progress == 1, PINK, BLUE)
        ax.scatter(d.true_area_change, d.area, s=5, c=c, alpha=0.55, lw=0)
        lim = [min(-30, d.area.min()), max(120, d.area.max())]
        ax.plot([-20, 110], [-20, 110], "k--", lw=0.7)
        ax.set_xlim(-20, 110); ax.set_ylim(-100, 160)
        ax.set_title(name, fontsize=7.8, color=NAVY)
        ax.set_xlabel("True area change (%)")
        ax.grid(alpha=0.25, lw=0.5); ax.spines[["top", "right"]].set_visible(False)
        a = acc["oracle" if name.startswith("Oracle") else "pipeline_accepted"]
        ax.text(0.03, 0.95, f"r = {a['r']:.2f}\nMAE = {a['mae_pp']:.1f} pp", transform=ax.transAxes, va="top", fontsize=7)
    axes[0].set_ylabel("Measured area change (%)")
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_area_accuracy.png", dpi=220)
    plt.close(fig)

    # ---------------- 5) per-group AUROC bar chart (best two features per group, full pipeline)
    NICE = {"area": "area", "eq_diameter": "equivalent diameter", "max_diameter": "max. diameter", "perimeter": "perimeter",
            "asymmetry": "asymmetry index", "asym_major": "A1 (major axis)", "asym_minor": "A2 (minor axis)",
            "compactness": "compactness", "fractal_dim": "fractal dimension", "radial_cv": "radial irregularity",
            "border_sharpness": "border sharpness", "solidity": "solidity", "convexity": "convexity", "eccentricity": "eccentricity",
            "dL_skin": "lightness vs skin (ΔL*)", "da_skin": "Δa* vs skin", "db_skin": "Δb* vs skin", "dE_skin": "contrast ΔE",
            "colour_heterogeneity": "heterogeneity", "n_colours": "no. of colours", "blue_gray_frac": "blue-grey fraction",
            "dark_frac": "dark fraction", "L_mean": "mean L*", "L_std": "SD of L*", "glcm_contrast": "GLCM contrast",
            "glcm_homogeneity": "GLCM homogeneity", "glcm_energy": "GLCM energy", "glcm_correlation": "GLCM correlation",
            "lbp_entropy": "LBP entropy"}
    best = tab.sort_values("auroc", ascending=False).groupby("group").head(2)
    order = ["Size", "Asymmetry", "Border", "Shape", "Colour", "Texture"]
    best["g"] = pd.Categorical(best.group, order)
    best = best.sort_values(["g", "auroc"], ascending=[True, False]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.2, 3.3))
    ys = np.arange(len(best))
    ax.barh(ys + 0.19, best.auroc, 0.38, color=BLUE, label="Full pipeline (U-Net masks, estimated registration)")
    ax.barh(ys - 0.19, best.auroc_oracle, 0.38, color="#9DC3E6", label="Oracle (true masks and transforms)")
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r.group}: {NICE.get(r.feature, r.feature)}" for r in best.itertuples()], fontsize=6.8)
    ax.axvline(0.5, color="k", lw=0.6, ls=":")
    ax.set_xlim(0.4, 1.0); ax.set_xlabel("AUROC, progressing vs stable (change from first to last visit)")
    ax.legend(frameon=False, fontsize=6.5, loc="upper center", bbox_to_anchor=(0.45, 1.13), ncol=2)
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="x", alpha=0.25, lw=0.5)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_feature_auroc.png", dpi=220)
    plt.close(fig)

    # ---------------- 6) measuring in the native frame vs after resampling into the baseline frame
    wpath = "/home/claude/melanotrack_ml/cache/seq/visits_warped.csv"
    if os.path.exists(wpath):
        w = pd.read_csv(wpath)
        w = w[w.split == "test"]
        wp = per_lesion_change(w, "f_")
        keys = set(zip(pipe.image_id, pipe.version)) & set(zip(wp.image_id, wp.version))
        sel = lambda d: d[[k in keys for k in zip(d.image_id, d.version)]]
        A_, B_ = sel(pipe), sel(wp)
        comp = []
        for f in ("perimeter", "compactness", "fractal_dim", "convexity", "solidity", "radial_cv", "asymmetry",
                  "border_sharpness", "glcm_contrast", "glcm_energy", "lbp_entropy", "dE_skin", "area"):
            row = dict(feature=f)
            for name, d in (("native", A_), ("resampled", B_)):
                st, pr = d[d.progress == 0][f], d[d.progress == 1][f]
                au = roc_auc_score(d.progress, d[f])
                row.update({f"{name}_stable_mean": st.mean(), f"{name}_stable_sd": st.std(), f"{name}_auroc": max(au, 1 - au)})
            comp.append(row)
        comp = pd.DataFrame(comp)
        comp.to_csv(f"{OUT}/frame_comparison.csv", index=False)
        print(comp.round(3).to_string())
        # visit-1 -> visit-2 jump in stable lesions (per-visit means), both methods
        jump = {}
        for name, d in (("native", te), ("resampled", w)):
            st = d[d.version == "stable"]
            jump[name] = {f: [float(st[st.t == t][f"f_{f}"].mean()) for t in range(4)] for f in ("compactness", "perimeter", "glcm_contrast")}
        summary["frame_visit_means_stable"] = jump

    json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=2)
    print(json.dumps(summary, indent=2))
    print(tab.round(3).to_string())


if __name__ == "__main__":
    main()
