"""Week-9 part B: temporal models and image + temporal feature fusion for progression-risk prediction.

Each ISIC 2017 lesion has a simulated 'progressing' and 'stable' 4-visit sequence (build_sequences.py).
A scenario draws, per lesion, whether it progresses: P(progress | melanoma) = p_mel, P(progress | benign) = p_ben.
Endpoints
  A  'progressed' (project definition, Week 4 M8): biopsy-confirmed melanoma OR documented change.
  B  melanoma only (change is just a correlated risk factor).
Models
  image_last   logistic regression on the last-visit EfficientNet-B0 embedding (image only)
  change_only  logistic regression on handcrafted change features (temporal only)
  early_fusion logistic regression on [image PCA-64, change features]
  late_fusion  logistic regression stacked on the two single-source scores (fitted on validation)
  gru_attn     GRU + attention over per-visit [image PCA-32, descriptors, time]   (sequence model)
  transformer  2-layer Transformer encoder over the same per-visit tokens
  gru_noimg    GRU over per-visit descriptors and time only (ablation)
"""
import sys, os, json, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import roc_auc_score, average_precision_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from features import FEATURE_GROUPS

torch.set_num_threads(int(os.environ.get("THREADS", 2)))
OUT = "/home/claude/melanotrack_ml/results/week9"
os.makedirs(OUT, exist_ok=True)
SIZE = ["area", "eq_diameter", "max_diameter", "perimeter"]
FEATS = [f for g in FEATURE_GROUPS.values() for f in g]
CHG_FEATS = ["area", "max_diameter", "asymmetry", "compactness", "radial_cv", "solidity", "dE_skin", "dL_skin",
             "db_skin", "colour_heterogeneity", "n_colours", "dark_frac", "blue_gray_frac", "glcm_contrast", "lbp_entropy"]


def load():
    v = pd.read_csv("/home/claude/melanotrack_ml/cache/seq/visits.csv")
    e = np.load("/home/claude/melanotrack_ml/cache/emb/visits_effb0.npz")
    key = {k: i for i, k in enumerate(e["ids"])}
    v["emb_idx"] = [key[f"{a}_{b}_v{c}"] for a, b, c in zip(v.image_id, v.version, v.t)]
    v = v.sort_values(["image_id", "version", "t"]).reset_index(drop=True)
    # fill rare missing descriptors (empty predicted masks) by carrying the previous visit forward
    fcols = [f"f_{f}" for f in FEATS]
    v[fcols] = v.groupby(["image_id", "version"])[fcols].transform(lambda s: s.ffill().bfill())
    v[fcols] = v[fcols].fillna(v[fcols].median())
    return v, e["X"]


def draw_scenario(lesions, p_mel, p_ben, seed):
    rng = np.random.default_rng(seed)
    p = np.where(lesions.melanoma.values == 1, p_mel, p_ben)
    prog = rng.random(len(lesions)) < p
    return pd.Series(np.where(prog, "prog", "stable"), index=lesions.image_id.values)


def change_features(g):
    """g: one sequence (4 visits, sorted). Returns a dict of change descriptors."""
    m = g.month.values
    out = {}
    for f in CHG_FEATS:
        x = g[f"f_{f}"].values.astype(float)
        if f in SIZE:
            x = 100 * (x / max(x[0], 1e-6) - 1)
        out[f"d_{f}"] = x[-1] - x[0]
        out[f"s_{f}"] = np.polyfit(m, x, 1)[0]
        out[f"j_{f}"] = np.max(np.abs(np.diff(x)))
    out["reg_uncertain_frac"] = float((~g.reg_ok.values[1:].astype(bool)).mean())
    return out


def build_tables(v, X, choice):
    sel = v[v.version.values == choice.reindex(v.image_id).values]
    rows, seqs = [], []
    for iid, g in sel.groupby("image_id", sort=False):
        g = g.sort_values("t")
        r = dict(image_id=iid, split=g.split.iloc[0], melanoma=int(g.melanoma.iloc[0]), progress=int(g.progress.iloc[0]),
                 last_emb=int(g.emb_idx.iloc[-1]))
        r.update(change_features(g))
        rows.append(r)
        seqs.append(dict(image_id=iid, emb=g.emb_idx.values, feats=g[[f"f_{f}" for f in FEATS]].values.astype(np.float32),
                         month=g.month.values.astype(np.float32)))
    tab = pd.DataFrame(rows)
    tab["endpointA"] = ((tab.melanoma == 1) | (tab.progress == 1)).astype(int)
    tab["endpointB"] = tab.melanoma
    return tab, {s["image_id"]: s for s in seqs}


def fit_lr(Xtr, ytr, Xva, yva):
    sc = StandardScaler().fit(Xtr)
    best, bauc = None, -1
    for C in (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0):
        m = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(sc.transform(Xtr), ytr)
        a = roc_auc_score(yva, m.decision_function(sc.transform(Xva)))
        if a > bauc:
            best, bauc = (C, m), a
    return sc, best[1], best[0]


class SeqNet(nn.Module):
    def __init__(self, d_in, kind="gru", d=64, use_img=True):
        super().__init__()
        self.kind = kind
        self.proj = nn.Sequential(nn.Linear(d_in, d), nn.LayerNorm(d), nn.GELU(), nn.Dropout(0.2))
        if kind == "gru":
            self.rnn = nn.GRU(d, d, batch_first=True)
        else:
            self.pos = nn.Linear(2, d)
            layer = nn.TransformerEncoderLayer(d, 4, 2 * d, dropout=0.2, batch_first=True)
            self.rnn = nn.TransformerEncoder(layer, 2)
        self.att = nn.Linear(d, 1)
        self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(d, 1))

    def forward(self, x, tfeat):
        h = self.proj(x)
        if self.kind == "gru":
            h, _ = self.rnn(h)
        else:
            h = self.rnn(h + self.pos(tfeat))
        a = torch.softmax(self.att(torch.tanh(h)).squeeze(-1), dim=1)
        c = (a.unsqueeze(-1) * h).sum(1)
        return self.head(c).squeeze(-1), a


def seq_tensors(ids, seqs, Xemb_pca, fsc, use_img):
    xs, ts = [], []
    for i in ids:
        s = seqs[i]
        f = fsc.transform(s["feats"])
        rel = f - f[0:1]                                        # change vs baseline (standardised units)
        dt = np.diff(s["month"], prepend=s["month"][0])
        tf = np.stack([np.log1p(dt / 1.0) / 3.0, s["month"] / 18.0], 1)
        parts = [f, rel, tf]
        if use_img:
            parts.insert(0, Xemb_pca[s["emb"]])
        xs.append(np.concatenate(parts, 1))
        ts.append(tf)
    return torch.tensor(np.stack(xs), dtype=torch.float32), torch.tensor(np.stack(ts), dtype=torch.float32)


def train_seq(kind, use_img, tr_ids, va_ids, te_ids, y, seqs, Xemb_pca, fsc, seed=0, epochs=60):
    torch.manual_seed(seed); np.random.seed(seed)
    Xtr, Ttr = seq_tensors(tr_ids, seqs, Xemb_pca, fsc, use_img)
    Xva, Tva = seq_tensors(va_ids, seqs, Xemb_pca, fsc, use_img)
    Xte, Tte = seq_tensors(te_ids, seqs, Xemb_pca, fsc, use_img)
    ytr = torch.tensor(y.loc[tr_ids].values, dtype=torch.float32)
    yva = y.loc[va_ids].values
    net = SeqNet(Xtr.shape[-1], kind)
    pw = ((1 - ytr.mean()) / ytr.mean()).detach().clone()
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    best, bauc, bad = None, -1, 0
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(len(Xtr))
        for b in range(0, len(perm), 64):
            idx = perm[b:b + 64]
            logit, _ = net(Xtr[idx], Ttr[idx])
            loss = lossf(logit, ytr[idx])
            opt.zero_grad(); loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            pv, _ = net(Xva, Tva)
        a = roc_auc_score(yva, pv.numpy())
        if a > bauc + 1e-4:
            bauc, bad = a, 0
            best = {k: t.clone() for k, t in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 12:
                break
    net.load_state_dict(best)
    net.eval()
    with torch.no_grad():
        pt, att = net(Xte, Tte)
        pv, _ = net(Xva, Tva)
    return pt.numpy(), pv.numpy(), att.numpy()


def boot_ci(y, s, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() == y[i].max():
            continue
        aucs.append(roc_auc_score(y[i], s[i]))
    return np.percentile(aucs, [2.5, 97.5])


def sens_at_spec(y, s, spec=0.8):
    neg = np.sort(s[y == 0])
    thr = neg[int(np.ceil(spec * len(neg))) - 1]
    return float((s[y == 1] > thr).mean())


def run_scenario(v, X, p_mel, p_ben, seed, endpoints=("endpointA", "endpointB"), seq_models=True, save_preds=False):
    lesions = v.drop_duplicates("image_id")[["image_id", "melanoma", "split"]]
    choice = draw_scenario(lesions, p_mel, p_ben, seed)
    tab, seqs = build_tables(v, X, choice)
    tab = tab.set_index("image_id")
    tr, va, te = (tab[tab.split == s] for s in ("train", "val", "test"))
    chg_cols = [c for c in tab.columns if c[:2] in ("d_", "s_", "j_")] + ["reg_uncertain_frac"]
    # image embeddings: PCA fitted on training last-visit embeddings
    pca64 = PCA(64, random_state=0).fit(X[tr.last_emb.values])
    pca256 = PCA(min(256, len(tr) - 1), random_state=0).fit(X[tr.last_emb.values])
    pca32 = PCA(32, random_state=0).fit(X[tr.last_emb.values])
    Xp32 = pca32.transform(X)
    Xp32 /= Xp32[tr.last_emb.values].std(0, keepdims=True)
    fsc = StandardScaler().fit(np.concatenate([seqs[i]["feats"] for i in tr.index]))
    results, preds = [], {}
    for ep in endpoints:
        ytr, yva, yte = tr[ep].values, va[ep].values, te[ep].values
        sets = {
            "image_last": tuple(pca256.transform(X[d.last_emb.values]) for d in (tr, va, te)),
            "change_only": (tr[chg_cols].values, va[chg_cols].values, te[chg_cols].values),
            "early_fusion": tuple(np.concatenate([pca64.transform(X[d.last_emb.values]), d[chg_cols].values], 1) for d in (tr, va, te)),
        }
        scores = {}
        for name, (a, b, c) in sets.items():
            sc, m, C = fit_lr(a, ytr, b, yva)
            scores[name] = (m.decision_function(sc.transform(c)), m.decision_function(sc.transform(b)))
        # late fusion: stack the two single-source scores, fitted on the validation split
        Zva = np.stack([scores["image_last"][1], scores["change_only"][1]], 1)
        Zte = np.stack([scores["image_last"][0], scores["change_only"][0]], 1)
        lf = LogisticRegression(max_iter=1000).fit(Zva, yva)
        scores["late_fusion"] = (lf.decision_function(Zte), None)
        if seq_models:
            y_all = tab[ep]
            todo = (("gru_attn", "gru", True), ("transformer", "transformer", True), ("gru_noimg", "gru", False))
            if seq_models == "gru_only":
                todo = todo[:1]
            for name, kind, use_img in todo:
                pt, pv, att = train_seq(kind, use_img, list(tr.index), list(va.index), list(te.index), y_all, seqs, Xp32, fsc)
                scores[name] = (pt, pv)
                if name == "gru_attn" and save_preds:
                    preds[f"{ep}__attention"] = pd.DataFrame(att, index=te.index, columns=[f"v{k}" for k in range(att.shape[1])])
        for name, (s, _) in scores.items():
            lo, hi = boot_ci(yte, s)
            results.append(dict(p_mel=p_mel, p_ben=p_ben, seed=seed, endpoint=ep, model=name,
                                auroc=roc_auc_score(yte, s), auroc_lo=lo, auroc_hi=hi,
                                auprc=average_precision_score(yte, s), sens_at_spec80=sens_at_spec(yte, s),
                                prevalence=yte.mean(), n_test=len(yte)))
            if save_preds:
                preds[f"{ep}__{name}"] = s
    if save_preds:
        preds["test_index"] = te.index.values
        preds["labels"] = te[["melanoma", "progress", "endpointA", "endpointB"]]
    return pd.DataFrame(results), preds


if __name__ == "__main__":
    t0 = time.time()
    v, X = load()
    main, preds = run_scenario(v, X, 0.7, 0.25, seed=0, save_preds=True)
    main.to_csv(f"{OUT}/temporal_main.csv", index=False)
    print(main.round(3).to_string(), flush=True)
    import pickle
    pickle.dump(preds, open(f"{OUT}/temporal_preds.pkl", "wb"))
    # robustness over scenario draws (linear models only, fast)
    reps = pd.concat([run_scenario(v, X, 0.7, 0.25, seed=s, seq_models=False)[0] for s in range(1, 6)])
    reps.to_csv(f"{OUT}/temporal_repeats.csv", index=False)
    # sensitivity analysis over how often benign lesions also change, incl. a control where change is unrelated
    sens = []
    for p_mel, p_ben in ((0.7, 0.1), (0.7, 0.4), (0.7, 0.55), (0.4, 0.4)):
        r, _ = run_scenario(v, X, p_mel, p_ben, seed=0, seq_models="gru_only")
        sens.append(r)
        print(p_mel, p_ben, f"{time.time() - t0:.0f}s", flush=True)
    pd.concat(sens).to_csv(f"{OUT}/temporal_sensitivity.csv", index=False)
    print("done", f"{time.time() - t0:.0f}s")
