"""Simulated longitudinal visit sequences built from real dermoscopic images, and the per-visit
processing pipeline (segmentation -> registration to baseline -> descriptors).

The real image is used as the LATEST visit. Earlier visits are generated backwards in time:
  * progressing lesion: smaller (total area growth G over the follow-up), asymmetric growth
    direction, lighter and more uniform colour at earlier visits;
  * stable lesion: true size jitter of about 3 % only.
Every visit then gets independent acquisition changes (camera pose, illumination, blur, noise).
"""
import numpy as np
import cv2
from simulate import radial_deform, colour_regress, camera_matrix, apply_camera, photometric, random_camera

MONTHS = np.array([0.0, 6.0, 12.0, 18.0])


def sequence_params(rng, progress):
    jitter = np.array([0.0, rng.uniform(-1, 1), rng.uniform(-1.5, 1.5), rng.uniform(-2, 2)])
    months = MONTHS + jitter
    if progress:
        return dict(progress=1, months=months, G=float(rng.uniform(1.3, 2.0)), asym=float(rng.uniform(0.2, 0.8)),
                    phi0=float(rng.uniform(0, 2 * np.pi)), colour=float(rng.uniform(0.3, 0.9)))
    return dict(progress=0, months=months, G=1.0, asym=0.0, phi0=0.0, colour=0.0)


def simulate_sequence(img, mask, params, rng):
    months = params["months"]
    T = months[-1]
    visits = []
    for t, tau in enumerate(months):
        frac = tau / T
        if params["progress"]:
            rel = (1 + (params["G"] - 1) * frac) / params["G"]
        else:
            rel = 1.0 if t == len(months) - 1 else float(1 + rng.normal(0, 0.03))
        if abs(rel - 1) > 1e-3:
            v_img, v_mask = radial_deform(img, mask, rel, params["asym"], params["phi0"])
        else:
            v_img, v_mask = img.copy(), mask.copy()
        if params["colour"] > 0:
            v_img = colour_regress(v_img, v_mask, params["colour"] * (1 - frac))
        cam = random_camera(rng)
        C = camera_matrix(cam["theta"], cam["scale"], cam["tx"], cam["ty"])
        a_img, a_mask = apply_camera(v_img, v_mask, C)
        a_img = photometric(a_img, rng)
        visits.append(dict(t=t, month=float(tau), img=a_img, true_mask=a_mask, C=C,
                           true_rel_area=float(rel), true_area_px=float(v_mask.sum())))
    return visits


def true_follow_to_base(C_base, C_t):
    """True transform from visit-t pixel coords to baseline-visit pixel coords."""
    inv_t = cv2.invertAffineTransform(C_t)
    A = np.vstack([C_base, [0, 0, 1]]) @ np.vstack([inv_t, [0, 0, 1]])
    return A[:2]
