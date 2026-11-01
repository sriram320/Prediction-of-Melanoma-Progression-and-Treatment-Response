"""Collect every number the Week-5/7/9 documents quote into results/numbers.json (single source of truth)."""
import json, os
import numpy as np
import pandas as pd

R = "/home/claude/melanotrack_ml/results"
C = "/home/claude/melanotrack_ml/cache"


def rd(path, **kw):
    return pd.read_csv(path, **kw) if os.path.exists(path) else None


def js(path):
    return json.load(open(path)) if os.path.exists(path) else None


def recs(df):
    return None if df is None else json.loads(df.to_json(orient="records"))


N = {"data": js(f"{C}/index.json")}
d17 = rd(f"{C}/isic2017_index.csv")
if d17 is not None:
    N["data"]["test_dx"] = d17[d17.split == "test"].dx.value_counts().to_dict()
    N["data"]["all_dx"] = d17.dx.value_counts().to_dict()

# ---------------- Week 5
w5 = {}
w5["unet"] = js(f"{R}/week5/unet_training.json")
w5["seg"] = recs(rd(f"{R}/week5/segmentation_summary.csv"))
bydx = rd(f"{R}/week5/segmentation_by_dx.csv")
w5["seg_by_dx"] = None if bydx is None else json.loads(bydx.set_index("method").to_json(orient="index"))
w5["seg_conf"] = js(f"{R}/week5/segmentation_confidence.json")
w5["reg"] = recs(rd(f"{R}/week5/registration_summary_all.csv"))
w5["reg_examples"] = js(f"{R}/week5/reg_examples.json")
raw = rd(f"{R}/week5/registration_raw_all.csv")
if raw is not None:
    g = raw[(raw.method == "sift_skin_v2") & (raw.scenario == "acquisition_plus_growth")]
    w5["reg_v2_growth_flagged_err_median"] = float(g[g.fallback].mean_err.median()) if g.fallback.any() else None
    from PIL import Image
    te = d17[d17.split == "test"].reset_index(drop=True)
    frac = {i: float((np.asarray(Image.open(te["mask"][i])) > 127).mean()) for i in range(len(te))}
    g = g.assign(frac=g.idx.map(frac))
    w5["flag_frac_median_flagged"] = float(g[g.fallback].frac.median())
    w5["flag_frac_median_accepted"] = float(g[~g.fallback].frac.median())
    w5["flag_rate_lt20"] = float(g[g.frac < 0.2].fallback.mean())
    w5["flag_rate_40_60"] = float(g[(g.frac >= 0.4) & (g.frac < 0.6)].fallback.mean())
    w5["flag_rate_gt60"] = float(g[g.frac >= 0.6].fallback.mean())
N["w5"] = w5

# ---------------- Week 7
N["w7"] = {"summary": js(f"{R}/week7/summary.json"), "features": recs(rd(f"{R}/week7/feature_change_table.csv")),
           "traj": recs(rd(f"{R}/week7/trajectories.csv")), "example": js(f"{R}/week7/example.json"),
           "frame": recs(rd(f"{R}/week7/frame_comparison.csv"))}

# ---------------- Week 9
N["w9"] = {"baselines": recs(rd(f"{R}/week9/baselines.csv")), "baselines_meta": js(f"{R}/week9/baselines_meta.json"),
           "temporal": recs(rd(f"{R}/week9/temporal_main.csv")), "sensitivity": recs(rd(f"{R}/week9/temporal_sensitivity.csv")),
           "extra": js(f"{R}/week9/extra.json")}
reps = rd(f"{R}/week9/temporal_repeats.csv")
if reps is not None:
    N["w9"]["repeats"] = recs(reps.groupby(["endpoint", "model"]).auroc.agg(["mean", "std", "min", "max"]).reset_index())

def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


json.dump(clean(N), open(f"{R}/numbers.json", "w"), indent=1, default=float, allow_nan=False)
print("numbers.json written; keys:", {k: list(v.keys()) if isinstance(v, dict) else type(v).__name__ for k, v in N.items()})
