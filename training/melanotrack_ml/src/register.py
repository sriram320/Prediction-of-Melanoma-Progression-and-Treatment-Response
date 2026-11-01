"""Cross-visit registration of a follow-up image to a reference (baseline) image.

All methods return a 2x3 matrix A that maps follow-up pixel coordinates into the reference frame,
plus a dict of diagnostics. Proposed method: SIFT matches restricted to skin around the lesion,
RANSAC similarity transform, quality score, identity check and a mask-moment fallback.
"""
import cv2
import numpy as np
from scipy import ndimage as ndi

_SIFT = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.008)
MIN_INLIERS = 16  # below this the estimate is unreliable (Week-5 ablation)


def _moments(mask):
    ys, xs = np.nonzero(mask)
    c = np.array([xs.mean(), ys.mean()])
    cov = np.cov(np.stack([xs - c[0], ys - c[1]]))
    evals, evecs = np.linalg.eigh(cov)
    v = evecs[:, -1]
    ang = np.arctan2(v[1], v[0])
    return c, ang, len(xs)


def plausible(A, smin=0.5, smax=2.0, tmax=256.0):
    """Reject degenerate transforms (NaN, extreme scale/shear, huge shifts)."""
    if A is None or not np.all(np.isfinite(A)):
        return False
    sv = np.linalg.svd(A[:, :2], compute_uv=False)
    return bool(sv.min() > smin and sv.max() < smax and np.abs(A[:, 2]).max() < tmax)


def _sim(c_src, c_dst, dtheta, s):
    ca, sa = np.cos(dtheta) * s, np.sin(dtheta) * s
    R = np.array([[ca, -sa], [sa, ca]])
    t = c_dst - R @ c_src
    return np.hstack([R, t[:, None]])


def _best_axis_rotation(mov, ref, A_candidates):
    """Principal axes are ambiguous by 180 degrees: pick the candidate with best image agreement."""
    best, bs = None, -2
    g_ref = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY).astype(np.float32)
    for A in A_candidates:
        w = cv2.warpAffine(cv2.cvtColor(mov, cv2.COLOR_RGB2GRAY).astype(np.float32), A, ref.shape[1::-1],
                           borderMode=cv2.BORDER_REFLECT101)
        s = np.corrcoef(w.ravel(), g_ref.ravel())[0, 1]
        if s > bs:
            best, bs = A, s
    return best


def reg_identity(ref, mov, m_ref, m_mov):
    return np.array([[1, 0, 0], [0, 1, 0]], float), {}


def reg_moments(ref, mov, m_ref, m_mov, with_scale=True):
    c_r, a_r, n_r = _moments(m_ref)
    c_m, a_m, n_m = _moments(m_mov)
    s = np.sqrt(n_r / n_m) if with_scale else 1.0
    cands = [_sim(c_m, c_r, a_r - a_m + k * np.pi, s) for k in (0, 1)]
    return _best_axis_rotation(mov, ref, cands), {}


def reg_ecc(ref, mov, m_ref, m_mov):
    A0, _ = reg_moments(ref, mov, m_ref, m_mov, with_scale=False)
    g_r = cv2.GaussianBlur(cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY), (0, 0), 1.5).astype(np.float32)
    g_m = cv2.GaussianBlur(cv2.cvtColor(mov, cv2.COLOR_RGB2GRAY), (0, 0), 1.5).astype(np.float32)
    # ECC estimates the warp from reference coords to moving coords; start from inverse of A0
    W = cv2.invertAffineTransform(A0).astype(np.float32)
    try:
        _, W = cv2.findTransformECC(g_r, g_m, W, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
        Ainv = cv2.invertAffineTransform(W)
        if not plausible(Ainv):
            return A0, {"ok": False}
        return Ainv, {"ok": True}
    except cv2.error:
        return A0, {"ok": False}


def _frame_mask(img, border=10, erode=6):
    """Usable field of view: excludes the dark dermatoscope frame (eroded) and a border band."""
    m = (img.max(axis=2) > 35)
    m = ndi.binary_erosion(m, iterations=erode)
    m[:border] = m[-border:] = False
    m[:, :border] = m[:, -border:] = False
    return m.astype(np.uint8)


def skin_region(mask, img, ring_frac=None, gap=4):
    """Skin outside the lesion; optionally only a ring of width ring_frac * equivalent diameter."""
    lesion = ndi.binary_dilation(mask > 0, iterations=gap)
    if ring_frac is None:
        region = ~lesion
    else:
        d_eq = 2 * np.sqrt(mask.sum() / np.pi)
        outer = ndi.binary_dilation(mask > 0, iterations=max(8, int(ring_frac * d_eq)))
        region = outer & ~lesion
    return (region & (_frame_mask(img) > 0)).astype(np.uint8) * 255


def _sift(img, region):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    return _SIFT.detectAndCompute(g, region)


def reg_sift(ref, mov, m_ref, m_mov, region="skin", ring_frac=None, model="similarity",
             tau_reg=0.6, fallback=True):
    """SIFT + RANSAC. region='whole' uses every pixel (lesion included); 'skin' excludes the lesion."""
    if region == "whole":
        r_ref = _frame_mask(ref) * 255
        r_mov = _frame_mask(mov) * 255
    else:
        r_ref = skin_region(m_ref, ref, ring_frac)
        r_mov = skin_region(m_mov, mov, ring_frac)
    kr, dr = _sift(ref, r_ref)
    km, dm = _sift(mov, r_mov)
    info = {"kp_ref": len(kr), "kp_mov": len(km), "inliers": 0, "matches": 0, "fallback": False}
    A = None
    if dr is not None and dm is not None and len(kr) >= 8 and len(km) >= 8:
        bf = cv2.BFMatcher(cv2.NORM_L2)
        knn = bf.knnMatch(dm, dr, k=2)
        good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
        info["matches"] = len(good)
        if len(good) >= 6:
            src = np.float32([km[m.queryIdx].pt for m in good])
            dst = np.float32([kr[m.trainIdx].pt for m in good])
            A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                                 maxIters=4000, confidence=0.995)
            if A is not None:
                n_in = int(inl.sum())
                info["inliers"] = n_in
                if model == "affine" and n_in >= 30:
                    A2, inl2 = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
                    if A2 is not None:
                        A, n_in = A2, int(inl2.sum())
                        info["inliers"] = n_in
    if A is not None and not plausible(A):
        A = None
        info["implausible"] = True
    if A is None:
        info["q_reg"] = 0.0
        info["ok"] = False
    else:
        rho = info["inliers"] / max(1, info["matches"])
        # normalised cross-correlation of the warped follow-up on the reference skin region
        g_r = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY).astype(np.float32)
        g_w = cv2.warpAffine(cv2.cvtColor(mov, cv2.COLOR_RGB2GRAY).astype(np.float32), A, ref.shape[1::-1],
                             borderMode=cv2.BORDER_CONSTANT)
        sel = skin_region(m_ref, ref, None) > 0
        a, b = g_r[sel], g_w[sel]
        ncc = float(np.corrcoef(a, b)[0, 1]) if sel.sum() > 50 else 0.0
        q = 0.5 * min(1.0, rho / 0.5) + 0.5 * max(0.0, ncc)
        warped_m = cv2.warpAffine(m_mov.astype(np.uint8), A, ref.shape[1::-1], flags=cv2.INTER_NEAREST)
        inter = np.logical_and(warped_m > 0, m_ref > 0).sum()
        union = np.logical_or(warped_m > 0, m_ref > 0).sum()
        same = inter / max(1, union) >= 0.3
        info.update(q_reg=q, ncc=ncc, rho=rho, same_lesion=bool(same), n_inliers_ok=info["inliers"] >= MIN_INLIERS)
        info["ok"] = bool(same and info["inliers"] >= MIN_INLIERS)
    if not info["ok"] and fallback:
        A, _ = reg_moments(ref, mov, m_ref, m_mov, with_scale=False)
        info["fallback"] = True
    if A is None:
        A = np.array([[1, 0, 0], [0, 1, 0]], float)
        info["failed"] = True
    return A, info


METHODS = {
    "none": lambda r, m, a, b: reg_identity(r, m, a, b),
    "moments_scale": lambda r, m, a, b: reg_moments(r, m, a, b, with_scale=True),
    "moments_rigid": lambda r, m, a, b: reg_moments(r, m, a, b, with_scale=False),
    "ecc_affine": reg_ecc,
    "sift_whole": lambda r, m, a, b: reg_sift(r, m, a, b, region="whole", fallback=False),
    "sift_skin": lambda r, m, a, b: reg_sift(r, m, a, b, region="skin", fallback=True),
}


def reg_ecc_skin(ref, mov, m_ref, m_mov, min_ncc=0.5):
    """Intensity-based (ECC) affine alignment that ignores the lesion: only skin pixels drive the fit."""
    A0, _ = reg_moments(ref, mov, m_ref, m_mov, with_scale=False)
    g_r = cv2.GaussianBlur(cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY), (0, 0), 1.5).astype(np.float32)
    g_m = cv2.GaussianBlur(cv2.cvtColor(mov, cv2.COLOR_RGB2GRAY), (0, 0), 1.5).astype(np.float32)
    skin_m = (skin_region(m_mov, mov, None, gap=6) > 0).astype(np.uint8)
    info = {"ok": False}
    if skin_m.sum() < 500:
        return A0, info
    W = cv2.invertAffineTransform(A0).astype(np.float32)
    try:
        _, W = cv2.findTransformECC(g_r, g_m, W, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-6), skin_m, 5)
    except cv2.error:
        return A0, info
    A = cv2.invertAffineTransform(W)
    if not plausible(A):
        return A0, info
    sel = skin_region(m_ref, ref, None) > 0
    g_w = cv2.warpAffine(g_m, A, ref.shape[1::-1], borderMode=cv2.BORDER_CONSTANT)
    ncc = float(np.corrcoef(g_r[sel], g_w[sel])[0, 1]) if sel.sum() > 50 else 0.0
    info.update(ncc=ncc, ok=bool(ncc >= min_ncc))
    return (A if info["ok"] else A0), info


def reg_hybrid(ref, mov, m_ref, m_mov):
    """Proposed: SIFT on skin -> masked ECC on skin -> rigid mask moments (last resort)."""
    A, info = reg_sift(ref, mov, m_ref, m_mov, region="skin", fallback=False)
    if info.get("ok"):
        info["stage"] = "sift_skin"
        return A, info
    A2, info2 = reg_ecc_skin(ref, mov, m_ref, m_mov)
    if info2.get("ok"):
        info.update(stage="ecc_skin", ok=True, fallback=False, ncc=info2.get("ncc"))
        return A2, info
    A3, _ = reg_moments(ref, mov, m_ref, m_mov, with_scale=False)
    info.update(stage="moments", ok=False, fallback=True)
    return A3, info


METHODS["ecc_skin"] = lambda r, m, a, b: reg_ecc_skin(r, m, a, b)
METHODS["hybrid_skin"] = reg_hybrid


def warp_to_ref(img, mask, A, shape):
    h, w = shape
    border = cv2.BORDER_REFLECT101 if plausible(A) else cv2.BORDER_CONSTANT
    wi = cv2.warpAffine(img, A, (w, h), flags=cv2.INTER_LINEAR, borderMode=border)
    wm = cv2.warpAffine(mask.astype(np.uint8), A, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    return wi, wm
