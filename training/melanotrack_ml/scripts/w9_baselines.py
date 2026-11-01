"""Week-9 part A: single-visit baselines on the real ISIC 2017 images (melanoma vs. benign).

Frozen ImageNet backbones (CNNs: ResNet-50, EfficientNet-B0, EfficientNet-B3; Transformer: Swin-T)
with a logistic-regression head (linear probe), a handcrafted ABCD-descriptor model on U-Net masks,
and image + descriptor fusion. Regularisation chosen on the validation split; test split reported
with 1,000-sample bootstrap 95 % CIs.
"""
import sys, os, json
import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from data import load_rgb
from features import describe, FEATURE_GROUPS
from seg_classical import keep_central_component

OUT = "/home/claude/melanotrack_ml/results/week9"
EMB = "/home/claude/melanotrack_ml/cache/emb"
os.makedirs(OUT, exist_ok=True)
NAMES = {"resnet50": "ResNet-50 (CNN)", "effb0": "EfficientNet-B0 (CNN)", "effb3": "EfficientNet-B3 (CNN)",
         "swin_t": "Swin-Tiny (Transformer)"}
PARAMS = {"resnet50": 25.6, "effb0": 5.3, "effb3": 12.2, "swin_t": 28.3}


def handcrafted(df):
    path = f"{EMB}/real_handcrafted.csv"
    if os.path.exists(path):
        return pd.read_csv(path).set_index("image_id")
    from unet import UNet, predict_prob
    torch.set_num_threads(2)
    model = UNet(pretrained=False)
    model.load_state_dict(torch.load("/home/claude/melanotrack_ml/cache/unet_r34.pt", map_location="cpu"))
    rows = []
    for b in range(0, len(df), 32):
        chunk = df.iloc[b:b + 32]
        imgs = [load_rgb(p) for p in chunk.img]
        probs, _ = predict_prob(model, imgs)
        for iid, im, p in zip(chunk.image_id, imgs, probs):
            m = keep_central_component(p > 0.5)
            f = describe(im, m) if m.sum() > 30 else None
            rows.append(dict(image_id=iid, **(f or {})))
    h = pd.DataFrame(rows)
    h.to_csv(path, index=False)
    return h.set_index("image_id")


def fit_eval(Xtr, ytr, Xva, yva, Xte):
    sc = StandardScaler().fit(Xtr)
    best = None
    for C in (0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0):
        m = LogisticRegression(C=C, max_iter=5000, class_weight="balanced").fit(sc.transform(Xtr), ytr)
        a = roc_auc_score(yva, m.decision_function(sc.transform(Xva)))
        if best is None or a > best[0]:
            best = (a, C, m)
    a, C, m = best
    return m.decision_function(sc.transform(Xte)), m.decision_function(sc.transform(Xva)), C, a


def metrics(y, s, s_val=None, y_val=None, seed=0):
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(1000):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            boots.append(roc_auc_score(y[i], s[i]))
    neg = np.sort(s[y == 0])
    thr80 = neg[int(np.ceil(0.8 * len(neg))) - 1]
    out = dict(auroc=roc_auc_score(y, s), auroc_lo=np.percentile(boots, 2.5), auroc_hi=np.percentile(boots, 97.5),
               auprc=average_precision_score(y, s), sens_at_spec80=float((s[y == 1] > thr80).mean()))
    if s_val is not None:  # threshold chosen on validation (Youden), applied to test
        fpr, tpr, th = roc_curve(y_val, s_val)
        t = th[np.argmax(tpr - fpr)]
        sens = float((s[y == 1] >= t).mean()); spec = float((s[y == 0] < t).mean())
        out.update(sensitivity=sens, specificity=spec, balanced_acc=(sens + spec) / 2)
    return out


if __name__ == "__main__":
    df = pd.read_csv("/home/claude/melanotrack_ml/cache/isic2017_index.csv").set_index("image_id")
    y = df.melanoma
    split = df.split
    tr, va, te = (df.index[split == s] for s in ("train", "val", "test"))
    rows, scores = [], {}
    for key in ("resnet50", "effb0", "effb3", "swin_t"):
        z = np.load(f"{EMB}/real_{key}.npz")
        E = pd.DataFrame(z["X"], index=z["ids"])
        s_te, s_va, C, va_auc = fit_eval(E.loc[tr].values, y[tr].values, E.loc[va].values, y[va].values, E.loc[te].values)
        scores[key] = s_te
        rows.append(dict(model=NAMES[key], features=f"{E.shape[1]}-d frozen embedding", params_M=PARAMS[key], C=C,
                         val_auroc=va_auc, **metrics(y[te].values, s_te, s_va, y[va].values)))
        print(rows[-1], flush=True)
    H = handcrafted(df.reset_index()).reindex(df.index)
    H = H.fillna(H.median())
    s_te, s_va, C, va_auc = fit_eval(H.loc[tr].values, y[tr].values, H.loc[va].values, y[va].values, H.loc[te].values)
    scores["abcd"] = s_te
    rows.append(dict(model="Handcrafted ABCD + texture (U-Net masks)", features=f"{H.shape[1]} descriptors", params_M=0, C=C,
                     val_auroc=va_auc, **metrics(y[te].values, s_te, s_va, y[va].values)))
    best_key = max(("resnet50", "effb0", "effb3", "swin_t"), key=lambda k: [r for r in rows if r["model"] == NAMES[k]][0]["val_auroc"])
    z = np.load(f"{EMB}/real_{best_key}.npz")
    E = pd.DataFrame(z["X"], index=z["ids"])
    pca = PCA(64, random_state=0).fit(E.loc[tr].values)
    F = np.concatenate([pca.transform(E.values), H.loc[E.index].values], 1)
    F = pd.DataFrame(F, index=E.index)
    s_te, s_va, C, va_auc = fit_eval(F.loc[tr].values, y[tr].values, F.loc[va].values, y[va].values, F.loc[te].values)
    scores["fusion"] = s_te
    rows.append(dict(model=f"{NAMES[best_key].split(' (')[0]} + ABCD descriptors (fusion)", features="PCA-64 embedding + descriptors",
                     params_M=PARAMS[best_key], C=C, val_auroc=va_auc, **metrics(y[te].values, s_te, s_va, y[va].values)))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/baselines.csv", index=False)
    np.savez(f"{OUT}/baseline_scores.npz", y=y[te].values, ids=np.array(list(te)), **scores)
    json.dump(dict(best_backbone_by_val=best_key, n_train=len(tr), n_val=len(va), n_test=len(te),
                   test_melanoma=int(y[te].sum())), open(f"{OUT}/baselines_meta.json", "w"), indent=2)
    print(res.round(3).to_string())
