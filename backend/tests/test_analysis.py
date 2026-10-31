"""P3: analysis jobs, the worker, the mock model and the safety wrapper (invariants 1-3, 7, 8)."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from tests.conftest import API, BACKEND_DIR, ML_APP_DIR, auth, second_hospital, staff_login
from tests.helpers import (analyse, db_conn, lesion_with_visits, new_lesion, new_patient, new_visit, run_worker,
                           unique_scan, upload)

def test_contract_copies_are_identical():
    backend = (BACKEND_DIR / "app" / "schemas" / "inference.py").read_text(encoding="utf-8")
    ml = (ML_APP_DIR / "contract.py").read_text(encoding="utf-8")
    assert backend == ml, "Keep backend/app/schemas/inference.py identical to ml_service/app/contract.py"


def test_full_analysis_flow(client, ml):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    admin = staff_login(client, "admin@demo.example")
    _, lesion, visits = lesion_with_visits(client, tech, 3)

    job_id = analyse(client, tech, lesion["id"])
    r = client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(doctor))
    assert r.status_code == 409 and r.json()["code"] == "JOB_IN_PROGRESS"
    assert client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(admin)).status_code == 403
    queued = client.get(f"{API}/jobs/{job_id}", headers=auth(tech)).json()
    assert queued["status"] == "queued" and queued["model"]["is_mock"] is True

    started = time.perf_counter()
    assert run_worker() == 1
    assert time.perf_counter() - started < 60  # NFR-01

    tech_view = client.get(f"{API}/jobs/{job_id}", headers=auth(tech)).json()
    assert tech_view["status"] == "succeeded" and "prediction_id" not in tech_view and "error" not in tech_view
    job = client.get(f"{API}/jobs/{job_id}", headers=auth(doctor)).json()
    assert job["prediction_id"] and job["error"] is None

    pred = client.get(f"{API}/predictions/{job['prediction_id']}", headers=auth(doctor)).json()
    assert pred["model"] == {"name": "mock", "version": "0.1.0", "is_mock": True}
    assert pred["is_baseline"] is False and pred["visit_id"] == visits[-1]["id"]
    assert pred["referral_flag"] or pred["risk_category"] in ("routine_monitoring", "shortened_interval",
                                                              "specialist_referral")
    if pred["referral_flag"]:
        assert pred["risk_category"] is None
    assert [f["visit_id"] for f in pred["visit_features"]] == [v["id"] for v in visits]
    assert pred["visit_features"][-1]["features"]["area_relative_to_baseline"] > 1.5

    exp = client.get(f"{API}/predictions/{pred['id']}/explanation", headers=auth(doctor)).json()
    assert set(exp["attention_weights"]) == {v["id"] for v in visits}
    assert exp["change_summary"] and exp["difference_map_file_id"] and exp["saliency_file_id"]
    assert client.get(f"{API}/files/{exp['difference_map_file_id']}/content", headers=auth(doctor)).status_code == 200
    assert client.get(f"{API}/files/{exp['saliency_file_id']}/content", headers=auth(admin)).status_code == 200

    # Technicians never see AI results.
    assert client.get(f"{API}/predictions/{pred['id']}", headers=auth(tech)).status_code == 403
    assert client.get(f"{API}/files/{exp['difference_map_file_id']}/content", headers=auth(tech)).status_code == 404
    assert "latest_prediction" not in client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()
    timeline = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()
    assert timeline["latest_prediction"]["id"] == pred["id"] and timeline["latest_job"]["status"] == "succeeded"

    with db_conn() as conn:
        masks = conn.execute("SELECT count(*) FROM images i JOIN visits v ON v.id = i.visit_id "
                             "WHERE v.lesion_id = %s AND i.mask_file_id IS NOT NULL AND i.mask_confidence > 0.6",
                             (lesion["id"],)).fetchone()[0]
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log WHERE entity_id IN (%s, %s)", (job_id, pred["id"]))]
    assert masks == 3 and set(actions) == {"job.create", "prediction.create"}

    jobs = client.get(f"{API}/jobs", headers=auth(tech), params={"lesion_id": lesion["id"]}).json()
    assert jobs["total"] == 1 and jobs["items"][0]["lesion_label"] == lesion["label"]


def test_single_visit_is_baseline_only(client, ml):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 1)
    job_id = analyse(client, tech, lesion["id"])
    run_worker()
    pred = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()["latest_prediction"]
    assert pred["is_baseline"] is True and pred["risk_score"] is None and pred["risk_category"] is None
    assert client.get(f"{API}/jobs/{job_id}", headers=auth(doctor)).json()["status"] == "succeeded"


def _latest(client, doctor, lesion_id):
    return client.get(f"{API}/lesions/{lesion_id}/timeline", headers=auth(doctor)).json()["latest_prediction"]


def test_model_error_becomes_referral(client, ml, monkeypatch):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 2)
    monkeypatch.setenv("MOCK_FORCE_ERROR", "1")
    job_id = analyse(client, tech, lesion["id"])
    run_worker()
    pred = _latest(client, doctor, lesion["id"])
    assert pred["referral_flag"] is True and pred["reason_codes"] == ["model_error"]
    assert pred["risk_category"] is None and pred["risk_score"] is None and "MOCK_FORCE_ERROR" in pred["model_error"]
    job = client.get(f"{API}/jobs/{job_id}", headers=auth(doctor)).json()
    assert job["status"] == "succeeded" and "500" in job["error"]  # fail-safe result stored, not a failed job


def test_timeout_becomes_referral(client, ml, monkeypatch):
    from app.core.config import settings

    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 2)
    original = type(ml.adapter).predict

    def slow(self, seq, images):
        time.sleep(2.5)
        return original(self, seq, images)

    monkeypatch.setattr(type(ml.adapter), "predict", slow)
    monkeypatch.setattr(settings, "inference_timeout_s", 1)
    analyse(client, tech, lesion["id"])
    run_worker()
    pred = _latest(client, doctor, lesion["id"])
    assert pred["referral_flag"] is True and pred["reason_codes"] == ["model_error"]
    assert "within 1 s" in pred["model_error"]


@pytest.mark.parametrize("response,expected", [
    (httpx.ConnectError("down"), "unreachable"),
    (httpx.Response(200, json={"model_name": "mock", "model_version": "0.1.0", "is_mock": True}), "neither"),
    (httpx.Response(200, json={"model_name": "other", "model_version": "9", "is_mock": False,
                               "risk_score": 0.1, "risk_category": "routine_monitoring"}), "active model"),
    (httpx.Response(200, json={"model_name": "mock", "model_version": "0.1.0", "is_mock": True,
                               "risk_score": 7}), "Invalid model output"),
])
def test_unusable_model_responses_become_referrals(client, monkeypatch, response, expected):
    from app.services import ml_client

    def handler(request):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(ml_client, "transport", httpx.MockTransport(handler))
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 2)
    analyse(client, tech, lesion["id"])
    run_worker()
    pred = _latest(client, doctor, lesion["id"])
    assert pred["referral_flag"] is True and pred["risk_category"] is None and pred["reason_codes"] == ["model_error"]
    assert expected in pred["model_error"]


def test_safety_wrapper_rules():
    from app.schemas.inference import ImageResult, PredictionOutput
    from app.services.inference import apply_safety_wrapper

    model = SimpleNamespace(name="mock", version="0.1.0", is_mock=True)
    base = dict(model_name="mock", model_version="0.1.0", is_mock=True, risk_score=0.8,
                risk_category="specialist_referral")

    ok = apply_safety_wrapper(PredictionOutput(**base), None, model=model, visit_count=3, confirmed_image_ids=set())
    assert (ok.referral_flag, ok.risk_category, ok.risk_score) == (False, "specialist_referral", 0.8)

    # Reason codes without the flag still mean referral, and referral always clears the category.
    coded = apply_safety_wrapper(PredictionOutput(**base, reason_codes=["ambiguous_prediction"]), None, model=model,
                                 visit_count=3, confirmed_image_ids=set())
    assert coded.referral_flag is True and coded.risk_category is None

    low_seg = PredictionOutput(**base, images=[ImageResult(image_id="a", mask_confidence=0.3)])
    r = apply_safety_wrapper(low_seg, None, model=model, visit_count=3, confirmed_image_ids=set())
    assert r.referral_flag and r.reason_codes == ["segmentation_low_confidence"] and r.risk_category is None
    r = apply_safety_wrapper(low_seg, None, model=model, visit_count=3, confirmed_image_ids={"a"})
    assert r.referral_flag is False  # a doctor confirmed that mask

    single = apply_safety_wrapper(PredictionOutput(**base), None, model=model, visit_count=1, confirmed_image_ids=set())
    assert single.is_baseline and single.risk_score is None and single.risk_category is None

    failed = apply_safety_wrapper(None, "boom", model=model, visit_count=3, confirmed_image_ids=set())
    assert failed.referral_flag and failed.reason_codes == ["model_error"] and failed.risk_category is None


def test_analysis_preconditions(client, ml, admin_token):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")

    p = new_patient(client, tech, consent_status=False)
    lesion = new_lesion(client, tech, p["id"])
    visit = new_visit(client, tech, lesion["id"], "2025-06-01")
    r = client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(tech))
    assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED"
    client.patch(f"{API}/patients/{p['id']}", headers=auth(tech), json={"consent_status": True})
    r = client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(tech))
    assert r.status_code == 409 and r.json()["code"] == "NO_SCANS"

    upload(client, tech, visit["id"], [("a.jpg", unique_scan(0))])
    client.patch(f"{API}/visits/{visit['id']}", headers=auth(doctor), json={"excluded": True, "reason": "Wrong spot"})
    r = client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(tech), json={"visit_id": visit["id"]})
    assert r.status_code == 409 and r.json()["code"] == "NO_SCANS"

    _, other_admin = second_hospital(client, admin_token)
    assert client.post(f"{API}/lesions/{lesion['id']}/analyze", headers=auth(other_admin)).status_code == 403
    other_jobs = client.get(f"{API}/jobs", headers=auth(other_admin)).json()["items"]
    assert all(j["lesion_id"] != lesion["id"] for j in other_jobs)


def test_rerun_keeps_history_and_stats_count_latest_only(client, ml):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    _, lesion, visits = lesion_with_visits(client, tech, 2)
    before = client.get(f"{API}/hospital/stats", headers=auth(doctor)).json()["pending_reviews"]
    first = analyse(client, doctor, lesion["id"])
    run_worker()
    second = analyse(client, doctor, lesion["id"], visit_id=visits[-1]["id"])
    run_worker()
    p1 = client.get(f"{API}/jobs/{first}", headers=auth(doctor)).json()["prediction_id"]
    p2 = client.get(f"{API}/jobs/{second}", headers=auth(doctor)).json()["prediction_id"]
    assert p1 != p2 and _latest(client, doctor, lesion["id"])["id"] == p2
    assert client.get(f"{API}/predictions/{p1}", headers=auth(doctor)).status_code == 200
    after = client.get(f"{API}/hospital/stats", headers=auth(doctor)).json()["pending_reviews"]
    assert after == before + 1


def test_stale_running_jobs_are_retried_then_failed(client, ml):
    from app.core.db import SessionLocal
    from app.services.inference import requeue_stale

    tech = staff_login(client, "tech@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 1)
    job_id = analyse(client, tech, lesion["id"])
    old = datetime.now(timezone.utc) - timedelta(hours=1)

    def stale(attempts):
        with db_conn() as conn:
            conn.execute("UPDATE inference_jobs SET status = 'running', started_at = %s, attempts = %s "
                         "WHERE id = %s", (old, attempts, job_id))

    async def requeue():
        async with SessionLocal() as db:
            return await requeue_stale(db)

    stale(1)
    assert asyncio.run(requeue()) == 1
    assert client.get(f"{API}/jobs/{job_id}", headers=auth(tech)).json()["status"] == "queued"
    stale(3)
    asyncio.run(requeue())
    assert client.get(f"{API}/jobs/{job_id}", headers=auth(tech)).json()["status"] == "failed"
    assert run_worker() == 0


def test_model_input_is_deidentified(client, monkeypatch):
    from app.services import ml_client

    seen = {}

    def handler(request):
        body = request.content
        start = body.index(b'name="payload"')
        payload = body[body.index(b"\r\n\r\n", start) + 4:]
        seen["payload"] = json.loads(payload[:payload.index(b"\r\n--")])
        seen["raw"] = body
        return httpx.Response(503)

    monkeypatch.setattr(ml_client, "transport", httpx.MockTransport(handler))
    tech = staff_login(client, "tech@demo.example")
    p, lesion, _ = lesion_with_visits(client, tech, 2, full_name="Zaheer Unique-Name", phone="+919812345678",
                                      medical_history={"prior_melanoma": True, "notes": "lives at 12 MG Road"})
    analyse(client, tech, lesion["id"])
    run_worker()
    payload = seen["payload"]
    assert payload["lesion_ref"].startswith(p["pseudonym_id"])
    assert payload["clinical"] == {"age_band": p["age_band"], "sex": "female", "anatomical_site": "posterior_torso",
                                   "fitzpatrick_type": 3, "history": {"prior_melanoma": True}}
    for secret in (b"Zaheer", b"9812345678", b"MG Road", p["mrn"].encode(), p["id"].encode()):
        assert secret not in seen["raw"]
