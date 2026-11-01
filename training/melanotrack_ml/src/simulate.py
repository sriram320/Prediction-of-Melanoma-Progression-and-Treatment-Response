"""Simulated follow-up visits from a real dermoscopic image.

Two kinds of change are applied, each with known ground truth:
  * lesion change: non-uniform radial growth or shrinkage of the lesion (area factor, asymmetry)
    plus optional darkening / blue-grey colour change inside the lesion;
  * acquisition change ("nuisance"): camera rotation, scale and shift, illumination, blur, noise.
"""
import cv2
import numpy as np
from scipy import ndimage as ndi


def lesion_polar_radius(mask, c, n_ang=360):
    """Boundary radius R(phi) of a (roughly star-shaped) lesion around centre c (vectorised ray casting)."""
    h, w = mask.shape
    angs = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    rs = np.arange(0, np.hypot(h, w), 0.5)
    xs = np.rint(c[0] + np.cos(angs)[:, None] * rs[None]).astype(int)
    ys = np.rint(c[1] + np.sin(angs)[:, None] * rs[None]).astype(int)
    ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    inside = np.zeros(xs.shape, bool)
    inside[ok] = mask[ys[ok], xs[ok]] > 0
    last = np.where(inside.any(1), inside.shape[1] - 1 - np.argmax(inside[:, ::-1], axis=1), 0)
    R = rs[last]
    R = ndi.gaussian_filter1d(R, 3, mode="wrap")
    return angs, np.maximum(R, 1.0)


def _k_profile(angs, g, asym, phi0):
    return 1.0 + g * (1.0 + asym * np.cos(angs - phi0))


def solve_g(R, angs, area_factor, asym, phi0):
    """Find g so that the deformed lesion has the requested area factor."""
    base = np.sum(R ** 2)
    lo, hi = -0.9 / (1 + abs(asym)), 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        k = _k_profile(angs, mid, asym, phi0)
        f = np.sum((k * R) ** 2) / base
        if f < area_factor:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def radial_deform(img, mask, area_factor, asym=0.0, phi0=0.0, margin=0.45):
    """Grow (>1) or shrink (<1) the lesion radially; skin beyond a margin is unchanged.

    Returns warped image, warped mask and the backward maps used.
    """
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    c = np.array([xs.mean(), ys.mean()])
    angs, R = lesion_polar_radius(mask, c)
    g = solve_g(R, angs, area_factor, asym, phi0)
    k = _k_profile(angs, g, asym, phi0)
    Rn = k * R
    W = margin * R.mean() + 6.0
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    dx, dy = xx - c[0], yy - c[1]
    r = np.hypot(dx, dy)
    phi = np.mod(np.arctan2(dy, dx), 2 * np.pi)
    idx = phi / (2 * np.pi) * len(angs)
    i0 = np.floor(idx).astype(int) % len(angs)
    i1 = (i0 + 1) % len(angs)
    t = idx - np.floor(idx)
    Rp = (1 - t) * R[i0] + t * R[i1]
    Rnp = (1 - t) * Rn[i0] + t * Rn[i1]
    rs = r.copy()
    inner = r <= Rnp
    rs[inner] = r[inner] * (Rp[inner] / Rnp[inner])
    band = (r > Rnp) & (r < Rnp + W)
    slope = (Rnp + W - Rp) / W
    rs[band] = Rp[band] + (r[band] - Rnp[band]) * slope[band]
    scale = np.where(r > 1e-6, rs / np.maximum(r, 1e-6), 1.0)
    mapx = (c[0] + dx * scale).astype(np.float32)
    mapy = (c[1] + dy * scale).astype(np.float32)
    out = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
    m = cv2.remap(mask.astype(np.uint8), mapx, mapy, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    return out, m


def colour_change(img, mask, strength, rng, blue=True):
    """Darkening plus an optional blue-grey blotch inside the lesion (strength 0..1)."""
    if strength <= 0:
        return img
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return img
    # smooth random field restricted to the lesion
    field = ndi.gaussian_filter(rng.standard_normal((h, w)), 10)
    field = (field - field.min()) / (np.ptp(field) + 1e-6)
    soft = ndi.gaussian_filter(mask.astype(np.float32), 3)
    wgt = soft * (0.5 + field)
    lab[..., 0] -= 22 * strength * wgt                      # darker
    if blue:
        j = rng.integers(len(xs))
        cy, cx = ys[j], xs[j]
        rad = max(4.0, 0.35 * np.sqrt(len(xs) / np.pi))
        yy, xx = np.mgrid[:h, :w]
        blob = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * rad ** 2)) * soft
        lab[..., 2] -= 30 * strength * blob                   # towards blue
        lab[..., 1] -= 8 * strength * blob                    # less red
        lab[..., 0] -= 10 * strength * blob
    lab = np.clip(lab, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def colour_regress(img, mask, weight):
    """Move lesion colours towards a lighter, more uniform version (used to go back in time)."""
    if weight <= 0:
        return img
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    soft = ndi.gaussian_filter(mask.astype(np.float32), 3)[..., None]
    sel = mask > 0
    if sel.sum() < 10:
        return img
    med = np.median(lab[sel], axis=0)
    target = lab.copy()
    target[..., 0] = np.maximum(lab[..., 0], med[0]) + 10       # lighter, darkest parts lifted
    target[..., 1:] = 0.5 * lab[..., 1:] + 0.5 * med[1:]         # less variegated
    out = lab * (1 - weight * soft) + target * (weight * soft)
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def camera_matrix(theta_deg, scale, tx, ty, size=256):
    c = (size / 2.0, size / 2.0)
    M = cv2.getRotationMatrix2D(c, theta_deg, scale)
    M[:, 2] += (tx, ty)
    return M


def apply_camera(img, mask, M):
    h, w = mask.shape
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
    m = cv2.warpAffine(mask.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    return out, m


def photometric(img, rng, strength=1.0):
    x = img.astype(np.float32) / 255.0
    gain = 1 + strength * rng.uniform(-0.10, 0.10, 3)
    x = x * gain
    gamma = 1 + strength * rng.uniform(-0.15, 0.15)
    x = np.clip(x, 0, 1) ** gamma
    x = x + strength * rng.uniform(-0.04, 0.04)
    sig = strength * rng.uniform(0, 1.0)
    if sig > 0.2:
        x = cv2.GaussianBlur(x, (0, 0), sig)
    x = x + rng.normal(0, 0.008 * strength, x.shape)
    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


def random_camera(rng, rot=30, scale=0.12, shift=16):
    return dict(theta=float(rng.uniform(-rot, rot)), scale=float(np.exp(rng.uniform(-scale, scale))),
                tx=float(rng.uniform(-shift, shift)), ty=float(rng.uniform(-shift, shift)))
