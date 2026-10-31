"""Deterministic mock model for UI development and demos. NOT a diagnostic model; always reports is_mock=True.

Pipeline (model_integration.md §4), all at a 256 px working resolution:
segmentation  Otsu threshold on luminance, ignoring the dark dermoscope ring; largest inner component, holes filled;
              confidence = solidity (area / convex-hull area)
registration  centroid + principal-axis alignment to the baseline; quality = IoU of the size-normalised shapes
features      area, colour variation (Lab), asymmetry, border irregularity per visit
risk          sigmoid of area growth per 90 days + colour and asymmetry change, with a small hash-seeded offset
explanations  ΔE (Lab) difference map baseline vs latest; a saliency-style overlay on the latest image
"""
import base64
import hashlib
import io
import math
import os
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..contract import ImageResult, LesionSequenceInput, PredictionOutput, VisitResult

WORK = 256
SEG_CONFIDENCE_MIN = 0.6
REGISTRATION_MIN = 0.5
UNCERTAINTY_MAX = 0.35
QUALITY_MIN = 0.4
THRESHOLDS = (0.35, 0.65)  # routine < 0.35 <= shortened < 0.65 <= specialist referral


# ---------------------------------------------------------------- image helpers
def _small(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    img = Image.fromarray(rgb)
    scale = max(img.size) / WORK if max(img.size) > WORK else 1.0
    if scale > 1:
        img = img.resize((round(img.width / scale), round(img.height / scale)), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32), scale


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=256, range=(0, 256))
    total = hist.sum()
    if total == 0:
        return 128.0
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * centers) / np.maximum(w0, 1)
    m1 = ((hist * centers).sum() - np.cumsum(hist * centers)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centers[int(np.argmax(between))])


def _components(mask: np.ndarray) -> list[tuple[np.ndarray, bool]]:
    """4-connected components of a boolean array: (flat indices, touches_border)."""
    h, w = mask.shape
    seen = np.zeros(mask.shape, dtype=bool)
    flat = mask.ravel()
    out = []
    for start in np.flatnonzero(flat):
        if seen.flat[start]:
            continue
        seen.flat[start] = True
        queue, members, border = deque([start]), [], False
        while queue:
            p = queue.popleft()
            members.append(p)
            y, x = divmod(p, w)
            if y in (0, h - 1) or x in (0, w - 1):
                border = True
            for q, ok in ((p - w, y > 0), (p + w, y < h - 1), (p - 1, x > 0), (p + 1, x < w - 1)):
                if ok and flat[q] and not seen.flat[q]:
                    seen.flat[q] = True
                    queue.append(q)
        out.append((np.array(members), border))
    return out


def _hull_area(points: np.ndarray) -> float:
    pts = sorted(set(map(tuple, points.tolist())))
    if len(pts) < 3:
        return float(len(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return 0.5 * abs(sum(hull[i][0] * hull[(i + 1) % len(hull)][1] - hull[(i + 1) % len(hull)][0] * hull[i][1]
                         for i in range(len(hull))))


def _png_b64(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


_STOPS = [(0.0, (10, 14, 40)), (0.33, (23, 195, 217)), (0.66, (250, 200, 50)), (1.0, (240, 90, 70))]


def _colormap(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0, 1)
    out = np.zeros(v.shape + (3,), dtype=np.float32)
    for (t0, c0), (t1, c1) in zip(_STOPS, _STOPS[1:]):
        sel = (v >= t0) & (v <= t1)
        f = ((v - t0) / (t1 - t0))[sel][:, None]
        out[sel] = np.array(c0) * (1 - f) + np.array(c1) * f
    return out


def _overlay(base_rgb: np.ndarray, heat: np.ndarray) -> np.ndarray:
    gray = _luma(base_rgb)[..., None].repeat(3, axis=2)
    alpha = (0.7 * np.clip(heat * 1.4, 0, 1))[..., None]
    out = gray * (1 - alpha) + _colormap(heat) * alpha
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    return np.asarray(img.resize((img.width * 2, img.height * 2), Image.BILINEAR))


# ---------------------------------------------------------------- per-image analysis
class Analysis:
    def __init__(self, rgb: np.ndarray):
        self.height, self.width = rgb.shape[:2]
        self.small, self.scale = _small(rgb)
        gray = _luma(self.small)
        self.quality_score, self.quality_flags = self._quality(gray)
        self.mask = self._segment(gray)
        self.area = float(self.mask.sum())
        ys, xs = np.nonzero(self.mask)
        self.ok = self.area >= 30
        if self.ok:
            self.cy, self.cx = float(ys.mean()), float(xs.mean())
            cov = np.cov(np.stack([xs - self.cx, ys - self.cy]))
            evals, evecs = np.linalg.eigh(cov)
            major = evecs[:, int(np.argmax(evals))]
            self.theta = math.atan2(major[1], major[0])
            self.confidence = min(1.0, self.area / max(_hull_area(np.stack([ys, xs], axis=1)), 1.0))
            lab = _lab(self.small)[self.mask]
            self.colour_var = float(lab.std(axis=0).mean())
            self.asymmetry = self._asymmetry(ys, xs)
            inner = self.mask[1:-1, 1:-1] & self.mask[:-2, 1:-1] & self.mask[2:, 1:-1] & self.mask[1:-1, :-2] \
                & self.mask[1:-1, 2:]
            perimeter = float(self.mask[1:-1, 1:-1].sum() - inner.sum())
            self.irregularity = perimeter ** 2 / (4 * math.pi * self.area)
        else:
            self.cy, self.cx = self.small.shape[0] / 2, self.small.shape[1] / 2
            self.theta, self.confidence, self.colour_var, self.asymmetry, self.irregularity = 0.0, 0.0, 0.0, 0.0, 1.0

    @staticmethod
    def _quality(gray: np.ndarray) -> tuple[float, list[str]]:
        lap = 4 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
        sharp = float(lap.var())
        glare = float((gray > 245).mean())
        flags = (["blur"] if sharp < 8 else []) + (["glare"] if glare > 0.05 else [])
        score = 0.6 * min(sharp / 40, 1) + 0.4 * max(0.0, 1 - glare / 0.1)
        return round(score, 3), flags

    @staticmethod
    def _segment(gray: np.ndarray) -> np.ndarray:
        valid = gray > 30  # the dermoscope's black ring is never lesion
        if valid.sum() < 100:
            return np.zeros(gray.shape, dtype=bool)
        candidate = (gray < _otsu(gray[valid])) & valid
        inner = [(idx, len(idx)) for idx, border in _components(candidate) if not border]
        mask = np.zeros(gray.shape, dtype=bool)
        if not inner:
            return mask
        mask.flat[max(inner, key=lambda t: t[1])[0]] = True
        for idx, border in _components(~mask):  # fill holes
            if not border:
                mask.flat[idx] = True
        return mask

    def _asymmetry(self, ys: np.ndarray, xs: np.ndarray) -> float:
        c, s = math.cos(-self.theta), math.sin(-self.theta)
        u = (xs - self.cx) * c - (ys - self.cy) * s
        v = (xs - self.cx) * s + (ys - self.cy) * c
        mirrored = np.zeros_like(self.mask)
        c2, s2 = math.cos(self.theta), math.sin(self.theta)
        mx = np.round(u * c2 + v * s2 + self.cx).astype(int)  # reflect across the major axis (v -> -v)
        my = np.round(u * s2 - v * c2 + self.cy).astype(int)
        keep = (my >= 0) & (my < self.mask.shape[0]) & (mx >= 0) & (mx < self.mask.shape[1])
        mirrored[my[keep], mx[keep]] = True
        inter = float((mirrored & self.mask).sum())
        union = float((mirrored | self.mask).sum())
        return round(1 - inter / union, 4) if union else 0.0

    def normalised_shape(self, flip: bool = False, size: int = 96) -> np.ndarray:
        ys, xs = np.nonzero(self.mask)
        theta = self.theta + (math.pi if flip else 0.0)
        c, s = math.cos(-theta), math.sin(-theta)
        r = math.sqrt(self.area)
        u = ((xs - self.cx) * c - (ys - self.cy) * s) / r
        v = ((xs - self.cx) * s + (ys - self.cy) * c) / r
        grid = np.zeros((size, size), dtype=bool)
        gx = np.clip(np.round((u + 1.5) / 3 * (size - 1)).astype(int), 0, size - 1)
        gy = np.clip(np.round((v + 1.5) / 3 * (size - 1)).astype(int), 0, size - 1)
        grid[gy, gx] = True
        return np.asarray(Image.fromarray(grid.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 127

    def mask_png(self) -> str:
        img = Image.fromarray((self.mask * 255).astype(np.uint8)).resize((self.width, self.height), Image.NEAREST)
        return _png_b64(np.asarray(img))


def _registration(base: Analysis, other: Analysis) -> tuple[list[list[float]], float]:
    """Rigid transform (rotation + translation, original pixels) mapping `other` onto `base`, and its quality."""
    if not (base.ok and other.ok):
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 0.0
    ref = base.normalised_shape()
    best, flip = 0.0, False
    for f in (False, True):
        cand = other.normalised_shape(flip=f)
        union = float((ref | cand).sum())
        iou = float((ref & cand).sum()) / union if union else 0.0
        if iou > best:
            best, flip = iou, f
    angle = base.theta - (other.theta + (math.pi if flip else 0.0))
    c, s = math.cos(angle), math.sin(angle)
    ox, oy = other.cx * other.scale, other.cy * other.scale
    bx, by = base.cx * base.scale, base.cy * base.scale
    return [[c, -s, bx - (c * ox - s * oy)], [s, c, by - (s * ox + c * oy)], [0.0, 0.0, 1.0]], round(best, 4)


def _warp_to(base: Analysis, other: Analysis, matrix: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
    """Resamples `other` (small image and mask) into the baseline's small-image frame."""
    a = np.array(matrix)
    inv = np.linalg.inv(a)
    sb, so = base.scale, other.scale
    # output small px -> original baseline px -> original other px -> small other px
    m = np.diag([1 / so, 1 / so, 1]) @ inv @ np.diag([sb, sb, 1])
    coeffs = (m[0, 0], m[0, 1], m[0, 2], m[1, 0], m[1, 1], m[1, 2])
    size = (base.small.shape[1], base.small.shape[0])
    img = Image.fromarray(other.small.astype(np.uint8)).transform(size, Image.AFFINE, coeffs, Image.BILINEAR)
    msk = Image.fromarray((other.mask * 255).astype(np.uint8)).transform(size, Image.AFFINE, coeffs, Image.NEAREST)
    return np.asarray(img, dtype=np.float32), np.asarray(msk) > 127


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


class MockAdapter:
    name = "mock"
    version = "0.1.0"
    is_mock = True

    def load(self, artifact_dir: Path) -> None:
        # No weights. The version follows MODEL_DIR (/models/mock/<version>) so it matches the registry row.
        if artifact_dir.name and artifact_dir.name[0].isdigit():
            self.version = artifact_dir.name

    def health(self) -> dict:
        return {"model_name": self.name, "model_version": self.version, "is_mock": True, "device": "cpu"}

    def predict(self, seq: LesionSequenceInput, images: dict[str, np.ndarray]) -> PredictionOutput:
        if os.environ.get("MOCK_FORCE_ERROR", "0") == "1":
            raise RuntimeError("MOCK_FORCE_ERROR=1: simulated model failure")

        analyses = {iid: Analysis(arr) for iid, arr in images.items()}
        visits = [v for v in seq.visits if v.images]
        rep = {}  # visit_id -> representative image analysis (first dermoscopic image)
        for v in visits:
            chosen = next((i for i in v.images if i.modality == "dermoscopic"), v.images[0])
            rep[v.visit_id] = (chosen.image_id, analyses[chosen.image_id])
        base_id, base = rep[visits[0].visit_id]

        image_results, reg_quality = [], {}
        for v in visits:
            for img in v.images:
                an = analyses[img.image_id]
                matrix, quality = _registration(base, an) if img.image_id != base_id else (
                    [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 1.0)
                reg_quality[img.image_id] = quality
                image_results.append(ImageResult(
                    image_id=img.image_id, mask_png_b64=an.mask_png() if an.ok else None,
                    mask_confidence=round(an.confidence, 4), quality_score=an.quality_score,
                    quality_flags=an.quality_flags, registration_transform=matrix, registration_quality=quality))

        visit_results = [VisitResult(visit_id=v.visit_id, features={
            "area_relative_to_baseline": round(rep[v.visit_id][1].area / max(base.area, 1.0), 4),
            "colour_variation": round(rep[v.visit_id][1].colour_var, 3),
            "asymmetry": rep[v.visit_id][1].asymmetry,
            "border_irregularity": round(rep[v.visit_id][1].irregularity, 3),
        }) for v in visits]

        modality_mask = {m: any(i.modality == m for v in visits for i in v.images)
                         for m in ("dermoscopic", "clinical_photo", "3d_tbp")}
        modality_mask["metadata"] = bool(seq.clinical.age_band or seq.clinical.anatomical_site)
        out = dict(model_name=self.name, model_version=self.version, is_mock=True, images=image_results,
                   visits=visit_results, modality_mask=modality_mask, saliency_passed_check=True)

        last_id, last = rep[visits[-1].visit_id]
        sal = (1 - _lab(last.small)[..., 0] / 100) * last.mask
        sal = np.asarray(Image.fromarray((np.clip(sal, 0, 1) * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255
        out["saliency_png_b64"] = _png_b64(_overlay(last.small, sal / max(float(sal.max()), 1e-6)))

        if len(visits) < 2:
            out.update(attention_weights={visits[0].visit_id: 1.0}, change_summary=[
                f"Baseline recorded on {visits[0].visit_date:%d %b %Y}. Later visits will be compared with it."])
            if not base.ok or base.confidence < SEG_CONFIDENCE_MIN:
                out.update(referral_flag=True, reason_codes=["segmentation_low_confidence"])
            return PredictionOutput(**out)

        unsegmented = [v for v in visits if not rep[v.visit_id][1].ok]
        if unsegmented:  # no lesion found in a visit: measuring change would be meaningless
            out.update(referral_flag=True, reason_codes=["segmentation_low_confidence"],
                       attention_weights={v.visit_id: round(1 / len(visits), 4) for v in visits},
                       change_summary=[f"No lesion could be outlined in the visit of {v.visit_date:%d %b %Y}."
                                       for v in unsegmented])
            return PredictionOutput(**out)

        # Change between baseline and latest, plus visit-to-visit magnitudes for attention.
        first_v, last_v = visits[0], visits[-1]
        days = max(1, last_v.days_since_baseline - first_v.days_since_baseline)
        growth = last.area / max(base.area, 1.0) - 1
        colour_change = (last.colour_var - base.colour_var) / max(base.colour_var, 1.0)
        asym_change = last.asymmetry - base.asymmetry
        irr_change = (last.irregularity - base.irregularity) / max(base.irregularity, 1e-6)

        magnitudes = []
        for i, v in enumerate(visits):
            cur = rep[v.visit_id][1]
            prev = rep[visits[i - 1].visit_id][1] if i else cur
            magnitudes.append(abs(cur.area / max(prev.area, 1.0) - 1) + abs(cur.colour_var - prev.colour_var) / 20
                              + (0.02 if i == 0 else 0.0))
        top = max(magnitudes)
        exps = [math.exp(4 * (m - top)) for m in magnitudes]
        out["attention_weights"] = {v.visit_id: round(e / sum(exps), 4) for v, e in zip(visits, exps)}

        digest = hashlib.sha256("".join(sorted(i.sha256 for v in visits for i in v.images)).encode()).hexdigest()
        jitter = (int(digest[:8], 16) / 0xFFFFFFFF - 0.5) * 0.06
        # Growth dominates ("E" in ABCDE): ~0% a year -> ~0.12, ~100% -> ~0.3, ~200% -> ~0.6, ~300% -> ~0.85.
        z = (-2.0 + 5.0 * min(max(growth / (days / 90), -1), 3) + 1.5 * min(max(colour_change, -1), 3)
             + 2.0 * asym_change)
        risk = min(max(_sigmoid(z) + jitter, 0.01), 0.99)
        change = 1 - math.exp(-(abs(growth) + abs(colour_change) + 2 * abs(asym_change)))

        min_reg = min(reg_quality[rep[v.visit_id][0]] for v in visits)
        min_conf = min(rep[v.visit_id][1].confidence for v in visits)
        low_quality = [r for r in image_results if (r.quality_score or 0) < QUALITY_MIN]
        uncertainty = min(1.0, 0.06 + 0.45 * (1 - min_reg) + 0.25 * (1 - min_conf)
                          + 0.15 * len(low_quality) / max(len(image_results), 1))

        reasons = []
        if low_quality:
            reasons.append("low_image_quality")
        if min_reg < REGISTRATION_MIN:
            reasons.append("registration_uncertain")
        if min_conf < SEG_CONFIDENCE_MIN:
            reasons.append("segmentation_low_confidence")
        if uncertainty > UNCERTAINTY_MAX:
            reasons.append("model_disagreement")
        if any(abs(risk - t) < 0.015 for t in THRESHOLDS):
            reasons.append("ambiguous_prediction")
        category = ("routine_monitoring" if risk < THRESHOLDS[0]
                    else "shortened_interval" if risk < THRESHOLDS[1] else "specialist_referral")

        span = f"{first_v.visit_date:%d %b %Y} and {last_v.visit_date:%d %b %Y}"
        summary = [f"Lesion area {'increased' if growth > 0 else 'decreased'} by {_pct(growth)} between {span}."
                   if abs(growth) >= 0.05 else f"Lesion area is stable (within 5%) between {span}.",
                   f"Colour variation within the lesion {'increased' if colour_change > 0 else 'decreased'} by "
                   f"{_pct(colour_change)}." if abs(colour_change) >= 0.1 else "Colour variation is stable.",
                   f"Shape asymmetry {'increased' if asym_change > 0 else 'decreased'} "
                   f"({base.asymmetry:.2f} to {last.asymmetry:.2f})." if abs(asym_change) >= 0.05
                   else "Shape asymmetry is stable."]
        if irr_change > 0.15:
            summary.append("The border has become more irregular.")
        if min_reg < REGISTRATION_MIN:
            summary.append("The visits could not be aligned reliably; compare the images directly.")

        warped, warped_mask = _warp_to(base, last, [[*r] for r in next(
            x.registration_transform for x in image_results if x.image_id == last_id)])
        region = np.asarray(Image.fromarray(((base.mask | warped_mask) * 255).astype(np.uint8)).filter(
            ImageFilter.MaxFilter(9)), dtype=bool)
        delta = np.linalg.norm(_lab(warped) - _lab(base.small), axis=-1) * region
        out.update(
            risk_score=round(risk, 4), risk_category=None if reasons else category, change_score=round(change, 4),
            uncertainty_score=round(uncertainty, 4), referral_flag=bool(reasons), reason_codes=reasons,
            registration_warning=min_reg < REGISTRATION_MIN, change_summary=summary,
            difference_map_png_b64=_png_b64(_overlay(base.small, delta / 40.0)),
            treatment_response="pending" if seq.treatments else None,
        )
        return PredictionOutput(**out)
