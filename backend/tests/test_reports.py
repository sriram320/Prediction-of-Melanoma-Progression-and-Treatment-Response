"""P4: doctor review, worklist, lesion outlines, treatments and the report lifecycle (invariant 4)."""
import io
from datetime import date, datetime, timezone

import numpy as np
from PIL import Image as PILImage

from tests.conftest import API, auth, patient_login, second_hospital, staff_login
from tests.helpers import analyse, db_conn, lesion_with_visits, run_worker


def _analysed_lesion(client, tech, n_visits=2, **patient):
    p, lesion, visits = lesion_with_visits(client, tech, n_visits, **patient)
    analyse(client, tech, lesion["id"])
    run_worker()
    return p, lesion, visits


def _latest(client, doctor, lesion_id):
    return client.get(f"{API}/lesions/{lesion_id}/timeline", headers=auth(doctor)).json()["latest_prediction"]


def _review(client, token, prediction_id, category, reason=None):
    return client.post(f"{API}/predictions/{prediction_id}/review", headers=auth(token),
                       json={"final_category": category, "reason": reason})


def test_review_rules(client, ml):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    admin = staff_login(client, "admin@demo.example")
    _, lesion, _ = _analysed_lesion(client, tech)
    pred = _latest(client, doctor, lesion["id"])
    assert pred["referral_flag"] is False and pred["risk_category"], pred
    other = next(c for c in ("routine_monitoring", "shortened_interval", "specialist_referral")
                 if c != pred["risk_category"])

    assert _review(client, tech, pred["id"], pred["risk_category"]).status_code == 403
    assert _review(client, admin, pred["id"], pred["risk_category"]).status_code == 403
    r = _review(client, doctor, pred["id"], other)
    assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED"
    r = _review(client, doctor, pred["id"], pred["risk_category"])
    assert r.status_code == 201 and r.json()["decision"] == "confirmed" and r.json()["reviewer_name"] == "Dr. Kiran Rao"
    r = _review(client, doctor, pred["id"], other, "Clinically the border looks regular")
    assert r.json()["decision"] == "overridden"

    reviews = client.get(f"{API}/predictions/{pred['id']}/reviews", headers=auth(admin)).json()
    assert [x["decision"] for x in reviews] == ["overridden", "confirmed"]
    latest = _latest(client, doctor, lesion["id"])
    assert latest["reviewed"] is True and latest["latest_review"]["final_category"] == other
    with db_conn() as conn:
        details = [row[0] for row in conn.execute(
            "SELECT details->>'decision' FROM audit_log WHERE action = 'prediction.review' AND entity_id = %s",
            (pred["id"],))]
    assert sorted(details) == ["confirmed", "overridden"]


def test_referred_case_needs_a_reason(client, ml, monkeypatch):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 2)
    monkeypatch.setenv("MOCK_FORCE_ERROR", "1")
    analyse(client, tech, lesion["id"])
    run_worker()
    pred = _latest(client, doctor, lesion["id"])
    assert pred["referral_flag"] is True
    assert _review(client, doctor, pred["id"], "routine_monitoring").status_code == 422
    r = _review(client, doctor, pred["id"], "specialist_referral", "Model failed; clinical exam suggests excision")
    assert r.status_code == 201 and r.json()["decision"] == "overridden"


def test_worklist_orders_referrals_first_and_moves_reviewed(client, ml, monkeypatch, admin_token):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, scored, _ = _analysed_lesion(client, tech)
    _, baseline, _ = _analysed_lesion(client, tech, n_visits=1)
    _, referred, _ = lesion_with_visits(client, tech, 2)
    monkeypatch.setenv("MOCK_FORCE_ERROR", "1")
    analyse(client, tech, referred["id"])
    run_worker()

    pending = client.get(f"{API}/worklist", headers=auth(doctor), params={"page_size": 100}).json()["items"]
    ids = [i["lesion_id"] for i in pending]
    assert referred["id"] in ids and scored["id"] in ids and baseline["id"] not in ids
    assert pending[0]["referral_flag"] is True
    assert ids.index(referred["id"]) < ids.index(scored["id"])
    assert client.get(f"{API}/worklist", headers=auth(tech)).status_code == 403
    _, other_admin = second_hospital(client, admin_token)
    assert all(i["lesion_id"] != scored["id"] for i in
               client.get(f"{API}/worklist", headers=auth(other_admin)).json()["items"])

    pred = _latest(client, doctor, scored["id"])
    _review(client, doctor, pred["id"], pred["risk_category"])
    pending = client.get(f"{API}/worklist", headers=auth(doctor), params={"page_size": 100}).json()["items"]
    assert scored["id"] not in [i["lesion_id"] for i in pending]
    reviewed = client.get(f"{API}/worklist", headers=auth(doctor), params={"state": "reviewed"}).json()["items"]
    assert reviewed[0]["lesion_id"] == scored["id"] and reviewed[0]["final_category"] == pred["risk_category"]


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def test_outline_confirm_and_correct(client, ml):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 1)
    image = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()["visits"][0]["images"][0]
    r = client.put(f"{API}/images/{image['id']}/mask", headers=auth(doctor), data={"confirm": "true"})
    assert r.status_code == 409 and r.json()["code"] == "NO_MASK"

    analyse(client, tech, lesion["id"])
    run_worker()
    image = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()["visits"][0]["images"][0]
    assert image["mask_file_id"] and image["mask_confirmed"] is False
    tech_image = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()["visits"][0]["images"][0]
    assert tech_image["mask_file_id"] is None and tech_image["mask_confidence"] is None
    assert client.put(f"{API}/images/{image['id']}/mask", headers=auth(tech), data={"confirm": "true"}).status_code == 403

    r = client.put(f"{API}/images/{image['id']}/mask", headers=auth(doctor), data={"confirm": "true"})
    assert r.status_code == 200 and r.json()["mask_confirmed"] is True

    w, h = image["width"], image["height"]
    empty = np.zeros((h, w), np.uint8)
    for data, why in ((_png(empty), "empty"), (_png(np.zeros((h, w * 2), np.uint8) + 255), "shape"),
                      (b"not a png", "PNG")):
        r = client.put(f"{API}/images/{image['id']}/mask", headers=auth(doctor),
                       files={"file": ("mask.png", data, "image/png")})
        assert r.status_code == 422 and why in r.json()["detail"], (why, r.text)

    drawn = empty.copy()
    drawn[h // 3: 2 * h // 3, w // 3: 2 * w // 3] = 255
    small = PILImage.fromarray(drawn).resize((w // 2, h // 2))  # same shape, different size: resized server-side
    r = client.put(f"{API}/images/{image['id']}/mask", headers=auth(doctor),
                   files={"file": ("mask.png", _png(np.asarray(small)), "image/png")})
    assert r.status_code == 200 and r.json()["mask_confidence"] == 1.0
    corrected = r.json()["mask_file_id"]
    stored = PILImage.open(io.BytesIO(client.get(f"{API}/files/{corrected}/content", headers=auth(doctor)).content))
    assert stored.size == (w, h)

    analyse(client, tech, lesion["id"])  # a re-run must not overwrite the doctor's outline
    run_worker()
    again = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()["visits"][0]["images"][0]
    assert again["mask_file_id"] == corrected


def test_treatment_events(client):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 1)
    body = {"treatment_type": "excision", "treatment_date": "2026-03-01", "notes": "Margins 2 mm"}
    assert client.post(f"{API}/lesions/{lesion['id']}/treatment-events", headers=auth(tech), json=body).status_code == 403
    assert client.post(f"{API}/lesions/{lesion['id']}/treatment-events", headers=auth(doctor),
                       json={**body, "treatment_date": "2999-01-01"}).status_code == 422
    r = client.post(f"{API}/lesions/{lesion['id']}/treatment-events", headers=auth(doctor), json=body)
    assert r.status_code == 201 and r.json()["response_category"] == "pending"
    assert [t["treatment_type"] for t in client.get(f"{API}/lesions/{lesion['id']}/treatment-events",
                                                     headers=auth(tech)).json()] == ["excision"]
    assert client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()["treatment_events"]


def test_report_lifecycle_and_patient_visibility(client, ml):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    admin = staff_login(client, "admin@demo.example")
    patient = patient_login(client)
    patient_id = client.get(f"{API}/auth/me", headers=auth(patient)).json()["patient_id"]
    lesion = client.get(f"{API}/patients/{patient_id}/lesions", headers=auth(doctor)).json()[0]  # seeded 3 visits
    analyse(client, doctor, lesion["id"])
    run_worker()
    pred = _latest(client, doctor, lesion["id"])

    assert client.post(f"{API}/reports", headers=auth(tech), json={"lesion_id": lesion["id"]}).status_code == 403
    r = client.post(f"{API}/reports", headers=auth(doctor), json={"lesion_id": lesion["id"]})
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["status"] == "draft" and report["prediction_id"] == pred["id"]
    assert report["report_number"].startswith(f"MT-{date.today():%Y}-") and report["category_from_review"] is True
    assert report["final_category"] is None and "AI change summary" in report["doctor_notes"]
    dup = client.post(f"{API}/reports", headers=auth(doctor), json={"lesion_id": lesion["id"]})
    assert dup.status_code == 409 and dup.json()["code"] == "DRAFT_EXISTS"

    rid = report["id"]
    r = client.patch(f"{API}/reports/{rid}", headers=auth(doctor), json={"final_category": "routine_monitoring"})
    assert r.status_code == 422 and r.json()["code"] == "CATEGORY_FROM_REVIEW"
    r = client.post(f"{API}/reports/{rid}/sign", headers=auth(doctor))
    assert r.status_code == 409 and r.json()["code"] == "REVIEW_REQUIRED"

    category = pred["risk_category"] or "specialist_referral"
    _review(client, doctor, pred["id"], category, None if pred["risk_category"] else "Referred; reviewed clinically")
    r = client.patch(f"{API}/reports/{rid}", headers=auth(doctor), json={
        "patient_summary": "Your spot has grown a little. We would like to see you sooner.",
        "recommendation": "Follow-up visit in 3 months", "doctor_notes": "No regression structures."})
    assert r.status_code == 200
    assert client.post(f"{API}/reports/{rid}/release", headers=auth(admin)).json()["code"] == "NOT_SIGNED"

    # Drafts and signed-but-unreleased reports are invisible to patients and technicians.
    assert client.get(f"{API}/me/reports", headers=auth(patient)).json() == []
    assert client.get(f"{API}/reports/{rid}", headers=auth(tech)).status_code == 404
    r = client.post(f"{API}/reports/{rid}/sign", headers=auth(doctor))
    assert r.status_code == 200 and r.json()["status"] == "signed" and r.json()["has_pdf"]
    assert r.json()["final_category"] == category and r.json()["signed_by_name"] == "Dr. Kiran Rao"
    assert client.patch(f"{API}/reports/{rid}", headers=auth(doctor),
                        json={"recommendation": "x"}).json()["code"] == "REPORT_LOCKED"
    assert client.get(f"{API}/me/reports", headers=auth(patient)).json() == []
    assert client.get(f"{API}/reports/{rid}/pdf", headers=auth(patient)).status_code == 404
    assert client.get(f"{API}/reports", headers=auth(tech), params={"patient_id": patient_id}).json()["total"] == 0
    clinician = client.get(f"{API}/reports/{rid}/pdf?variant=clinician", headers=auth(doctor))
    assert clinician.status_code == 200 and clinician.content.startswith(b"%PDF")

    r = client.post(f"{API}/reports/{rid}/release", headers=auth(admin))
    assert r.status_code == 200 and r.json()["status"] == "released"
    mine = client.get(f"{API}/me/reports", headers=auth(patient)).json()
    assert [m["id"] for m in mine] == [rid] and mine[0]["final_category"] == category
    assert not {"risk_score", "prediction_id", "doctor_notes", "model"} & set(mine[0])
    assert client.get(f"{API}/me/overview", headers=auth(patient)).json()["latest_report"]["id"] == rid
    pdf = client.get(f"{API}/reports/{rid}/pdf?download=true", headers=auth(patient))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "attachment" in pdf.headers["content-disposition"]
    assert client.get(f"{API}/reports/{rid}/pdf?variant=clinician", headers=auth(patient)).status_code == 404
    assert client.get(f"{API}/reports/{rid}/pdf", headers=auth(tech)).status_code == 200
    assert client.get(f"{API}/reports/{rid}/pdf?variant=clinician", headers=auth(tech)).status_code == 404
    tech_view = client.get(f"{API}/reports/{rid}", headers=auth(tech)).json()
    assert tech_view["doctor_notes"] is None and tech_view["model"] is None

    # Amend: a new version replaces the old one for the patient only once it is released.
    v2 = client.post(f"{API}/reports/{rid}/amend", headers=auth(doctor)).json()
    assert v2["version"] == 2 and v2["report_number"].endswith("-V2") and v2["supersedes_id"] == rid
    assert client.post(f"{API}/reports/{rid}/amend", headers=auth(doctor)).json()["code"] == "AMENDMENT_EXISTS"
    client.patch(f"{API}/reports/{v2['id']}", headers=auth(doctor),
                 json={"recommendation": "Follow-up visit in 2 months"})
    client.post(f"{API}/reports/{v2['id']}/sign", headers=auth(doctor))
    assert [m["id"] for m in client.get(f"{API}/me/reports", headers=auth(patient)).json()] == [rid]
    client.post(f"{API}/reports/{v2['id']}/release", headers=auth(doctor))
    mine = client.get(f"{API}/me/reports", headers=auth(patient)).json()
    assert [m["id"] for m in mine] == [v2["id"]] and mine[0]["recommendation"] == "Follow-up visit in 2 months"
    assert client.get(f"{API}/reports/{rid}", headers=auth(doctor)).json()["status"] == "amended"
    assert client.get(f"{API}/reports/{rid}/pdf", headers=auth(patient)).status_code == 404

    with db_conn() as conn:
        actions = {row[0] for row in conn.execute(
            "SELECT action FROM audit_log WHERE entity_id IN (%s, %s)", (rid, v2["id"]))}
    assert {"report.create", "report.sign", "report.release", "report.amend", "report.download"} <= actions


def test_report_without_ai_result(client):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, lesion, _ = lesion_with_visits(client, tech, 1)
    report = client.post(f"{API}/reports", headers=auth(doctor), json={"lesion_id": lesion["id"]}).json()
    assert report["prediction_id"] is None and report["category_from_review"] is False
    r = client.post(f"{API}/reports/{report['id']}/sign", headers=auth(doctor))
    assert r.status_code == 422 and r.json()["code"] == "INCOMPLETE_REPORT"
    client.patch(f"{API}/reports/{report['id']}", headers=auth(doctor), json={
        "final_category": "routine_monitoring", "patient_summary": "Looks stable.", "recommendation": "Check in a year"})
    assert client.post(f"{API}/reports/{report['id']}/sign", headers=auth(doctor)).json()["status"] == "signed"


def test_patient_copy_never_contains_ai_details(monkeypatch):
    from app.services import report_pdf

    monkeypatch.setattr(report_pdf, "_fonts", lambda: (None, None))  # core font: text stays greppable
    original = report_pdf._ReportPDF.__init__

    def uncompressed(self, ctx, variant):
        original(self, ctx, variant)
        self.set_compression(False)

    monkeypatch.setattr(report_pdf._ReportPDF, "__init__", uncompressed)
    ctx = report_pdf.ReportContext(
        hospital_name="H", hospital_address=None, report_number="MT-2026-000999", version=1, supersedes_number=None,
        patient_name="Test Patient", mrn="T-1", date_of_birth=date(1980, 1, 1), lesion_label="L1",
        anatomical_site="posterior_torso", final_category="shortened_interval", patient_summary="Plain words.",
        recommendation="Come back soon.", doctor_notes="NOTE-FOR-CLINICIANS", signed_by="Dr. A",
        signed_by_registration=None, signed_at=datetime.now(timezone.utc), model_name="mock", model_version="0.1.0",
        is_mock=True, ai_category="shortened_interval", risk_score=0.6123, uncertainty_score=0.1456,
        change_summary=["AREA-CHANGE-SENTENCE"])
    patient = report_pdf.render(ctx, "patient")
    clinician = report_pdf.render(ctx, "clinician")
    for marker in (b"0.61", b"0.15", b"NOTE-FOR-CLINICIANS", b"AREA-CHANGE-SENTENCE", b"risk score"):
        assert marker not in patient and marker in clinician, marker
    for both in (b"Plain words.", b"MOCK MODEL - NOT FOR CLINICAL USE", b"final assessment by the signing clinician"):
        assert both in patient and both in clinician, both
