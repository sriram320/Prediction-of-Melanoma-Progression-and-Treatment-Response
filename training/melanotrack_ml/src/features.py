"""Per-visit lesion descriptors (ABCD-style + texture) used for change analysis across visits."""
import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import color
from skimage.feature import graycomatrix, graycoprops, local_binary_pattern

# Six dermoscopic reference colours (RGB), as commonly used in ABCD colour scoring
REF_COLOURS = {
    "white": (255, 255, 255), "red": (204, 51, 51), "light_brown": (153, 102, 51),
    "dark_brown": (51, 0, 0), "blue_gray": (51, 153, 153), "black": (0, 0, 0),
}
_REF_LAB = color.rgb2lab(np.array(list(REF_COLOURS.values()), np.float64)[None] / 255.0)[0]


def _largest_contour(mask):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cs, key=cv2.contourArea) if cs else None


def _asymmetry(mask):
    ys, xs = np.nonzero(mask)
    c = (xs.mean(), ys.mean())
    cov = np.cov(np.stack([xs - c[0], ys - c[1]]))
    evals, evecs = np.linalg.eigh(cov)
    ang = np.degrees(np.arctan2(evecs[1, -1], evecs[0, -1]))
    h, w = mask.shape
    pad = int(max(h, w) * 0.5)
    big = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    big[pad:pad + h, pad:pad + w] = mask
    M = cv2.getRotationMatrix2D((c[0] + pad, c[1] + pad), ang, 1.0)
    M[:, 2] += (big.shape[1] / 2 - (c[0] + pad), big.shape[0] / 2 - (c[1] + pad))
    al = cv2.warpAffine(big, M, big.shape[::-1], flags=cv2.INTER_NEAREST) > 0
    a = al.sum()
    a1 = np.logical_xor(al, al[::-1, :]).sum() / (2 * a)       # about the major axis
    a2 = np.logical_xor(al, al[:, ::-1]).sum() / (2 * a)       # about the minor axis
    ecc = np.sqrt(1 - evals[0] / evals[1]) if evals[1] > 0 else 0.0
    return float(a1), float(a2), float(ecc)


def _fractal_dimension(mask):
    edge = mask ^ ndi.binary_erosion(mask)
    sizes = np.array([2, 4, 8, 16, 32])
    counts = []
    for s in sizes:
        h, w = (np.array(edge.shape) // s) * s
        e = edge[:h, :w].reshape(h // s, s, w // s, s).any(axis=(1, 3))
        counts.append(max(1, e.sum()))
    k = np.polyfit(np.log(1 / sizes), np.log(counts), 1)[0]
    return float(k)


def describe(img, mask, skin_ring_px=12):
    """img: RGB uint8, mask: binary lesion mask in the same frame. Sizes are in pixels of that frame."""
    mask = mask > 0
    if mask.sum() < 30:
        return None
    cnt = _largest_contour(mask)
    area = float(mask.sum())
    perim = float(cv2.arcLength(cnt, True))
    hull = cv2.convexHull(cnt)
    hull_area = float(cv2.contourArea(hull)) + 1e-6
    hull_perim = float(cv2.arcLength(hull, True)) + 1e-6
    hp = hull[:, 0, :].astype(np.float64)
    dmax = float(np.max(np.linalg.norm(hp[:, None] - hp[None], axis=2))) if len(hp) > 1 else 0.0
    a1, a2, ecc = _asymmetry(mask)
    ys, xs = np.nonzero(mask)
    cy, cx = ys.mean(), xs.mean()
    pts = cnt[:, 0, :].astype(np.float64)
    rad = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)

    lab = color.rgb2lab(img / 255.0)
    L = lab[..., 0]
    les = lab[mask]
    ring = ndi.binary_dilation(mask, iterations=skin_ring_px) & ~ndi.binary_dilation(mask, iterations=3)
    ring &= img.max(axis=2) > 35
    skin = lab[ring] if ring.sum() > 30 else lab[~mask]
    skin_mean = skin.mean(0)
    les_mean = les.mean(0)
    # colour presence: nearest reference colour within dE76 < 30, counted if >= 5 % of lesion
    d = np.linalg.norm(les[:, None, :] - _REF_LAB[None], axis=2)
    nearest = d.argmin(1)
    close = d.min(1) < 30
    frac = np.array([(close & (nearest == k)).mean() for k in range(len(REF_COLOURS))])
    heter = float(np.linalg.norm(les - les_mean, axis=1).mean())
    # border sharpness: mean L* gradient magnitude on the boundary band
    gy, gx = np.gradient(ndi.gaussian_filter(L, 1.0))
    band = ndi.binary_dilation(mask, iterations=2) & ~ndi.binary_erosion(mask, iterations=2)
    sharp = float(np.hypot(gx, gy)[band].mean())

    # texture inside the lesion (L* quantised to 32 levels; level 0 reserved for background)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    Lc, mc = L[y0:y1, x0:x1], mask[y0:y1, x0:x1]
    q = np.zeros_like(Lc, dtype=np.uint8)
    q[mc] = 1 + np.clip((Lc[mc] / 100.0 * 31).astype(int), 0, 31)
    glcm = graycomatrix(q, [1, 2], [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4], levels=33, symmetric=True)
    glcm = glcm[1:, 1:].astype(np.float64)
    glcm /= glcm.sum(axis=(0, 1), keepdims=True) + 1e-12
    tex = {p: float(graycoprops(glcm, p).mean()) for p in ("contrast", "homogeneity", "energy", "correlation")}
    lbp = local_binary_pattern((Lc * 2.55).astype(np.uint8), 8, 1, method="uniform")[mc]
    hist = np.bincount(lbp.astype(int), minlength=10) / max(1, len(lbp))
    lbp_entropy = float(-(hist[hist > 0] * np.log2(hist[hist > 0])).sum())

    f = dict(
        area=area, eq_diameter=float(2 * np.sqrt(area / np.pi)), max_diameter=dmax, perimeter=perim,
        asym_major=a1, asym_minor=a2, asymmetry=(a1 + a2) / 2,
        compactness=perim ** 2 / (4 * np.pi * area), fractal_dim=_fractal_dimension(mask),
        radial_cv=float(rad.std() / rad.mean()), border_sharpness=sharp,
        solidity=area / hull_area, convexity=hull_perim / perim, eccentricity=ecc,
        L_mean=float(les_mean[0]), a_mean=float(les_mean[1]), b_mean=float(les_mean[2]),
        L_std=float(les[:, 0].std()), dL_skin=float(les_mean[0] - skin_mean[0]),
        da_skin=float(les_mean[1] - skin_mean[1]), db_skin=float(les_mean[2] - skin_mean[2]),
        dE_skin=float(np.linalg.norm(les_mean - skin_mean)), colour_heterogeneity=heter,
        n_colours=int((frac >= 0.05).sum()), blue_gray_frac=float(frac[4]), dark_frac=float(frac[3] + frac[5]),
        lbp_entropy=lbp_entropy, **{f"glcm_{k}": v for k, v in tex.items()},
    )
    return f


FEATURE_GROUPS = {
    "Size": ["area", "eq_diameter", "max_diameter", "perimeter"],
    "Asymmetry": ["asymmetry", "asym_major", "asym_minor"],
    "Border": ["compactness", "fractal_dim", "radial_cv", "border_sharpness"],
    "Shape": ["solidity", "convexity", "eccentricity"],
    "Colour": ["dL_skin", "da_skin", "db_skin", "dE_skin", "colour_heterogeneity", "n_colours", "blue_gray_frac",
               "dark_frac", "L_mean", "L_std"],
    "Texture": ["glcm_contrast", "glcm_homogeneity", "glcm_energy", "glcm_correlation", "lbp_entropy"],
}
