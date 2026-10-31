"""MockAdapter and /infer behaviour. Template for the real model: copy and point at test vectors (§5 step 5)."""
import base64
import hashlib
import io
import json
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def lesion(radius: float, *, seed: int = 1, size=(640, 480), dots: int = 0) -> bytes:
    """Brown blob on skin inside a dark dermoscope ring."""
    rng = np.random.default_rng(seed)
    h, w = size[1], size[0]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot(xx - w / 2, yy - h / 2)
    theta = np.arctan2(yy - h / 2, xx - w / 2)
    edge = radius * (1 + 0.1 * np.sin(3 * theta))
    img = np.array([198, 152, 122], np.float32) + rng.normal(0, 6, (h, w, 1))
    inside = r < edge
    img[inside] = np.array([90, 55, 40]) + rng.normal(0, 5, (int(inside.sum()), 1))
    for _ in range(dots):
        cy, cx = h / 2 + rng.uniform(-0.5, 0.5) * radius, w / 2 + rng.uniform(-0.5, 0.5) * radius
        img[np.hypot(xx - cx, yy - cy) < 5] = [35, 20, 15]
    img[r > 0.47 * w] = [10, 10, 10]
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def infer(images: list[bytes], *, days_apart: int = 120):
    start = date(2025, 1, 10)
    visits, files = [], []
    for i, data in enumerate(images):
        iid = f"img{i}"
        visits.append({"visit_id": f"v{i}", "visit_date": str(start + timedelta(days=i * days_apart)),
                       "days_since_baseline": i * days_apart,
                       "images": [{"image_id": iid, "modality": "dermoscopic",
                                   "sha256": hashlib.sha256(data).hexdigest()}]})
        files.append((iid, (f"{iid}.png", data, "image/png")))
    payload = {"lesion_ref": "MT-TEST-L1", "visits": visits,
               "clinical": {"age_band": "40-49", "sex": "female", "anatomical_site": "posterior_torso",
                            "fitzpatrick_type": 4}}
    return client.post("/infer", data={"payload": json.dumps(payload)}, files=files)


def test_health_reports_mock():
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["is_mock"] is True and body["model_name"] == "mock"


def test_growing_lesion_is_scored_with_explanations():
    r = infer([lesion(60, seed=1), lesion(80, seed=2, dots=3), lesion(105, seed=3, dots=8)])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["is_mock"] is True and 0 <= out["risk_score"] <= 1
    assert out["referral_flag"] or out["risk_category"] is not None
    if out["referral_flag"]:
        assert out["risk_category"] is None and out["reason_codes"]
    assert abs(sum(out["attention_weights"].values()) - 1) < 0.01
    assert max(out["attention_weights"], key=out["attention_weights"].get) != "v0"
    assert any("increased" in s for s in out["change_summary"])
    areas = [v["features"]["area_relative_to_baseline"] for v in out["visits"]]
    assert areas[0] == 1 and areas[2] > areas[1] > 1.3
    for key in ("difference_map_png_b64", "saliency_png_b64"):
        assert Image.open(io.BytesIO(base64.b64decode(out[key]))).format == "PNG"
    for img in out["images"]:
        assert img["mask_confidence"] > 0.6 and img["mask_png_b64"]
        assert img["registration_quality"] > 0.5


def test_stable_lesion_scores_lower_than_growing_one():
    stable = infer([lesion(80, seed=4), lesion(80, seed=5), lesion(81, seed=6)]).json()
    growing = infer([lesion(60, seed=7), lesion(85, seed=8, dots=4), lesion(115, seed=9, dots=9)]).json()
    assert stable["risk_score"] < growing["risk_score"]
    assert any("stable" in s for s in stable["change_summary"])


def test_results_are_deterministic():
    imgs = [lesion(70, seed=10), lesion(90, seed=11)]
    a, b = infer(imgs).json(), infer(imgs).json()
    assert a["risk_score"] == b["risk_score"] and a["attention_weights"] == b["attention_weights"]


def test_single_visit_is_a_baseline():
    out = infer([lesion(70, seed=12)]).json()
    assert out["risk_score"] is None and out["risk_category"] is None
    assert out["attention_weights"] == {"v0": 1.0} and "Baseline" in out["change_summary"][0]


def test_blank_image_cannot_be_segmented_and_is_referred():
    blank = io.BytesIO()
    Image.new("RGB", (400, 300), (190, 150, 120)).save(blank, "PNG")
    out = infer([blank.getvalue(), lesion(80, seed=13)]).json()
    assert out["referral_flag"] is True and out["risk_category"] is None
    assert "segmentation_low_confidence" in out["reason_codes"]


def test_forced_error_returns_500(monkeypatch):
    monkeypatch.setenv("MOCK_FORCE_ERROR", "1")
    r = infer([lesion(70, seed=14), lesion(80, seed=15)])
    assert r.status_code == 500 and "MOCK_FORCE_ERROR" in r.text


@pytest.mark.parametrize("payload,files", [
    ("not json", []),
    (json.dumps({"lesion_ref": "x", "visits": [], "clinical": {}}), []),
])
def test_bad_requests_are_rejected(payload, files):
    assert client.post("/infer", data={"payload": payload}).status_code == 422


def test_missing_image_part_is_rejected():
    data = lesion(70, seed=16)
    payload = {"lesion_ref": "x", "clinical": {}, "visits": [{
        "visit_id": "v0", "visit_date": "2025-01-01", "days_since_baseline": 0,
        "images": [{"image_id": "absent", "modality": "dermoscopic", "sha256": "0" * 64}]}]}
    r = client.post("/infer", data={"payload": json.dumps(payload)}, files=[("other", ("o.png", data, "image/png"))])
    assert r.status_code == 422 and "absent" in r.text
