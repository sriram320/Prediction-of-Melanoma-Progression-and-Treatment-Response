"""Classical lesion segmentation: automatic Otsu baseline and semi-automatic GrabCut."""
import cv2
import numpy as np
from scipy import ndimage as ndi


def _dark_corner_mask(img):
    """Vignette / black frame of the dermatoscope: very dark pixels connected to the image border."""
    v = img.max(axis=2)
    dark = (v < 40).astype(np.uint8)
    lab, n = ndi.label(dark)
    if n == 0:
        return np.zeros(dark.shape, bool)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    return np.isin(lab, border[border > 0])


def hair_suppress(img, k=11, thr=10):
    """DullRazor-style hair removal: black-hat on grey, threshold, inpaint."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (k, k))
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, kernel)
    hair = (bh > thr).astype(np.uint8)
    if hair.mean() < 0.002:
        return img, hair
    out = cv2.inpaint(img, cv2.dilate(hair, np.ones((3, 3), np.uint8)), 3, cv2.INPAINT_TELEA)
    return out, hair


def keep_central_component(mask, min_frac=0.002):
    lab, n = ndi.label(mask)
    if n == 0:
        return mask.astype(np.uint8)
    h, w = mask.shape
    yy, xx = np.mgrid[:h, :w]
    best, score = 0, -1e9
    for i in range(1, n + 1):
        comp = lab == i
        a = comp.sum()
        if a < min_frac * h * w:
            continue
        cy, cx = yy[comp].mean(), xx[comp].mean()
        d = np.hypot(cy - h / 2, cx - w / 2) / (0.5 * np.hypot(h, w))
        s = np.log(a) - 3.0 * d      # prefer large, central components
        if s > score:
            best, score = i, s
    if best == 0:
        return np.zeros_like(mask, dtype=np.uint8)
    return ndi.binary_fill_holes(lab == best).astype(np.uint8)


def otsu_segment(img):
    """Automatic baseline: hair removal, blue-channel/L* contrast, Otsu threshold, morphology."""
    clean, _ = hair_suppress(img)
    lab = cv2.cvtColor(clean, cv2.COLOR_RGB2LAB)
    chan = 0.5 * lab[..., 0].astype(np.float32) + 0.5 * clean[..., 2].astype(np.float32)
    chan = cv2.GaussianBlur(chan, (0, 0), 2.0)
    frame = _dark_corner_mask(img)
    vals = chan[~frame]
    vals8 = np.clip(vals, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(vals8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = (chan < t) & ~frame
    m = ndi.binary_opening(m, iterations=2)
    m = ndi.binary_closing(m, iterations=3)
    return keep_central_component(m)


def grabcut_segment(img, rect=None, init_mask=None, iters=5):
    """Semi-automatic GrabCut. rect = (x, y, w, h) drawn by the user, or an initial mask."""
    clean, _ = hair_suppress(img)
    bgr = cv2.cvtColor(clean, cv2.COLOR_RGB2BGR)
    mask = np.zeros(img.shape[:2], np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    if init_mask is not None:
        mask[:] = cv2.GC_PR_BGD
        er = ndi.binary_erosion(init_mask, iterations=4)
        dil = ndi.binary_dilation(init_mask, iterations=10)
        mask[init_mask > 0] = cv2.GC_PR_FGD
        mask[er] = cv2.GC_FGD
        mask[~dil] = cv2.GC_BGD
        if (mask == cv2.GC_FGD).sum() < 10:
            mask[init_mask > 0] = cv2.GC_PR_FGD
        cv2.grabCut(bgr, mask, None, bgd, fgd, iters, cv2.GC_INIT_WITH_MASK)
    else:
        cv2.grabCut(bgr, mask, tuple(int(v) for v in rect), bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    fg = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD))
    fg = ndi.binary_opening(fg, iterations=1)
    return keep_central_component(fg)


def user_box_from_mask(gt, margin=0.12, jitter=0.05, rng=None):
    """Simulated user input for evaluation: a box around the lesion with a margin and small jitter."""
    rng = rng or np.random.default_rng(0)
    ys, xs = np.nonzero(gt)
    h, w = gt.shape
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    bh, bw = y1 - y0 + 1, x1 - x0 + 1
    dy0, dy1, dx0, dx1 = (rng.uniform(-jitter, jitter, 4) + margin) * np.array([bh, bh, bw, bw])
    y0 = int(max(1, y0 - dy0)); y1 = int(min(h - 2, y1 + dy1))
    x0 = int(max(1, x0 - dx0)); x1 = int(min(w - 2, x1 + dx1))
    return (x0, y0, max(2, x1 - x0), max(2, y1 - y0))


def dice_iou(pred, gt):
    p, g = pred.astype(bool), gt.astype(bool)
    inter = (p & g).sum()
    s = p.sum() + g.sum()
    union = (p | g).sum()
    dice = 2 * inter / s if s else 1.0
    iou = inter / union if union else 1.0
    return float(dice), float(iou)


def boundary_hd95(pred, gt):
    """95th percentile symmetric boundary distance in pixels."""
    from scipy.ndimage import distance_transform_edt
    p, g = pred.astype(bool), gt.astype(bool)
    if p.sum() == 0 or g.sum() == 0:
        return float("nan")
    pb = p ^ ndi.binary_erosion(p)
    gb = g ^ ndi.binary_erosion(g)
    dg = distance_transform_edt(~gb)
    dp = distance_transform_edt(~pb)
    d = np.concatenate([dg[pb], dp[gb]])
    return float(np.percentile(d, 95))
