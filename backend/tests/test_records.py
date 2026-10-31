"""P2: patient registration, invites, lesions, visits, scan uploads and the timeline."""
import io

from PIL import Image as PILImage

from tests.conftest import API, auth, patient_login, second_hospital, staff_login
from tests.helpers import (db_conn, dicom_bytes, new_lesion, new_patient, new_visit, unique_pdf, unique_scan,
                           upload)


def test_register_and_search_patients(client):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech, mrn="mrn-search-1", full_name="Meera Nair", phone="+91 98450 11111")
    assert p["pseudonym_id"].startswith("MT-") and len(p["pseudonym_id"]) == 11
    assert p["has_account"] is False and p["age_band"] and p["phone"] == "+919845011111"

    for q in ("meera", "MRN-SEARCH", p["pseudonym_id"]):
        items = client.get(f"{API}/patients", headers=auth(tech), params={"q": q}).json()["items"]
        assert [i["id"] for i in items] == [p["id"]], q
    assert client.get(f"{API}/patients", headers=auth(tech), params={"q": "%"}).json()["total"] == 0

    r = client.post(f"{API}/patients", headers=auth(tech), json={
        "mrn": "MRN-SEARCH-1", "full_name": "Dup", "date_of_birth": "1990-01-01"})
    assert r.status_code == 409 and r.json()["code"] == "MRN_TAKEN"
    r = client.post(f"{API}/patients", headers=auth(tech), json={
        "mrn": "X-FUTURE", "full_name": "Future", "date_of_birth": "2999-01-01"})
    assert r.status_code == 422


def test_patient_update_audits_field_names_not_values(client):
    doctor = staff_login(client, "doctor@demo.example")
    p = new_patient(client, doctor, consent_status=False)
    r = client.patch(f"{API}/patients/{p['id']}", headers=auth(doctor), json={
        "phone": "+919811122233", "consent_status": True, "medical_history": {"prior_melanoma": True}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["consent_status"] is True and body["consent_at"] and body["medical_history"] == {"prior_melanoma": True}
    with db_conn() as conn:
        details = conn.execute("SELECT details::text FROM audit_log WHERE action = 'patient.update' "
                               "AND entity_id = %s", (p["id"],)).fetchone()[0]
    assert "phone" in details and "9811122233" not in details


def test_invite_code_activates_and_only_newest_works(client):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech, date_of_birth="1971-03-09")
    first = client.post(f"{API}/patients/{p['id']}/invite", headers=auth(tech)).json()["invite_code"]
    second = client.post(f"{API}/patients/{p['id']}/invite", headers=auth(tech)).json()["invite_code"]
    assert client.get(f"{API}/patients/{p['id']}", headers=auth(tech)).json()["pending_invite"]

    activate = {"date_of_birth": "1971-03-09", "email": f"{p['mrn'].lower()}@patients.example",
                "password": "PatientPass99"}
    assert client.post(f"{API}/auth/patient/activate", json={**activate, "invite_code": first}).status_code == 400
    r = client.post(f"{API}/auth/patient/activate", json={**activate, "invite_code": second.lower()})
    assert r.status_code == 201, r.text
    r = client.post(f"{API}/patients/{p['id']}/invite", headers=auth(tech))
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_ACTIVATED"
    assert client.get(f"{API}/patients/{p['id']}", headers=auth(tech)).json()["has_account"] is True


def test_lesions_visits_and_timeline(client):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    p = new_patient(client, tech, date_of_birth="1985-02-01")
    lesion = new_lesion(client, tech, p["id"], label="L1 - chest", site="anterior_torso")
    dup = client.post(f"{API}/patients/{p['id']}/lesions", headers=auth(tech),
                      json={"label": "l1 - CHEST", "anatomical_site": "anterior_torso"})
    assert dup.status_code == 409
    bad_site = client.post(f"{API}/patients/{p['id']}/lesions", headers=auth(tech),
                           json={"label": "L2", "anatomical_site": "elbow"})
    assert bad_site.status_code == 422

    new_visit(client, tech, lesion["id"], "2026-03-01")
    new_visit(client, tech, lesion["id"], "2025-09-15", device_model="DermLite DL5", polarised=True)
    for date_, code in (("2999-01-01", 422), ("1984-12-31", 422), ("2026-03-01", 409)):
        r = client.post(f"{API}/lesions/{lesion['id']}/visits", headers=auth(tech), json={"visit_date": date_})
        assert r.status_code == code, (date_, r.text)

    t_tech = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()
    assert [v["visit_date"] for v in t_tech["visits"]] == ["2025-09-15", "2026-03-01"]
    assert "latest_prediction" not in t_tech  # technicians never see AI results
    assert t_tech["analysable_visit_count"] == 0 and t_tech["patient"]["pseudonym_id"] == p["pseudonym_id"]
    t_doc = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()
    assert "latest_prediction" in t_doc and t_doc["latest_prediction"] is None
    lesions = client.get(f"{API}/patients/{p['id']}/lesions", headers=auth(doctor)).json()
    assert lesions[0]["visit_count"] == 2 and lesions[0]["first_visit_date"] == "2025-09-15"


def test_scan_upload_validates_dedupes_and_scores(client):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech)
    lesion = new_lesion(client, tech, p["id"])
    v1 = new_visit(client, tech, lesion["id"], "2025-11-01")
    v2 = new_visit(client, tech, lesion["id"], "2026-02-01")

    scan = unique_scan(0)
    img = PILImage.open(io.BytesIO(scan))
    exif = img.getexif()
    exif[0x8825] = {2: (12.0, 58.0, 0.0)}  # GPS position
    tagged = io.BytesIO()
    img.save(tagged, "JPEG", quality=92, exif=exif, comment=b"Meera Nair")
    small_png = io.BytesIO()
    PILImage.new("RGB", (300, 200), (20, 15, 15)).save(small_png, "PNG")

    r = upload(client, tech, v1["id"], [("tagged.jpg", tagged.getvalue()), ("notes.txt", b"hello world"),
                                       ("dark.png", small_png.getvalue()), ("../../evil name.jpg", unique_scan(1))])
    assert r.status_code == 200, r.text
    res = {x["filename"]: x for x in r.json()}
    assert res["tagged.jpg"]["image_id"] and res["tagged.jpg"]["quality_flags"] == []
    assert res["notes.txt"]["error"] and res["notes.txt"]["image_id"] is None
    assert set(res["dark.png"]["quality_flags"]) >= {"too_dark", "low_resolution"}
    assert "evil name.jpg" in res  # path components stripped

    content = client.get(f"{API}/files/{res['tagged.jpg']['file_id']}/content", headers=auth(tech))
    stored = PILImage.open(io.BytesIO(content.content))
    assert dict(stored.getexif()) == {} and b"Meera Nair" not in content.content

    again = upload(client, tech, v2["id"], [("same.jpg", tagged.getvalue())]).json()[0]
    assert again["duplicate"] is True and again["duplicate_visit_date"] == "2025-11-01" and again["error"]

    timeline = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()
    first = timeline["visits"][0]
    assert len(first["images"]) == 3 and "too_dark" in first["quality_flags"]
    assert first["quality_score"] == min(i["quality_score"] for i in first["images"])
    assert timeline["visits"][1]["images"] == []
    assert timeline["analysable_visit_count"] == 1


def test_dicom_upload_converts_and_keeps_original(client):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech)
    visit = new_visit(client, tech, new_lesion(client, tech, p["id"])["id"], "2026-01-05")
    res = upload(client, tech, visit["id"], [("scan.dcm", dicom_bytes())]).json()[0]
    assert res["image_id"] and "low_resolution" in res["quality_flags"], res
    shown = client.get(f"{API}/files/{res['file_id']}/content", headers=auth(tech))
    assert shown.headers["content-type"] == "image/png"
    with db_conn() as conn:
        source, device = conn.execute(
            "SELECT i.source_file_id, v.device_model FROM images i JOIN visits v ON v.id = i.visit_id "
            "WHERE i.id = %s", (res["image_id"],)).fetchone()
    assert source is not None and device == "FotoFinder Medicam 1000"
    assert client.get(f"{API}/files/{source}/content", headers=auth(tech)).status_code == 200


def test_upload_limits(client):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech)
    visit = new_visit(client, tech, new_lesion(client, tech, p["id"])["id"], "2026-01-06")
    r = upload(client, tech, visit["id"], [(f"f{i}.jpg", b"x") for i in range(11)])
    assert r.status_code == 422 and r.json()["code"] == "TOO_MANY_FILES"
    r = upload(client, tech, visit["id"], [("broken.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50), ("doc.pdf", unique_pdf())])
    assert all(x["error"] for x in r.json())


def test_only_doctors_exclude_visits(client):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    p = new_patient(client, tech)
    visit = new_visit(client, tech, new_lesion(client, tech, p["id"])["id"], "2026-01-07")
    body = {"excluded": True, "reason": "Wrong lesion photographed"}
    assert client.patch(f"{API}/visits/{visit['id']}", headers=auth(tech), json=body).status_code == 403
    r = client.patch(f"{API}/visits/{visit['id']}", headers=auth(doctor), json=body)
    assert r.status_code == 200 and r.json()["excluded"] is True
    assert client.patch(f"{API}/visits/{visit['id']}", headers=auth(doctor),
                        json={"excluded": False, "reason": ""}).status_code == 422
    with db_conn() as conn:
        details = conn.execute("SELECT details->>'reason' FROM audit_log WHERE action = 'visit.exclude' "
                               "AND entity_id = %s", (visit["id"],)).fetchone()[0]
    assert details == "Wrong lesion photographed"


def test_other_hospital_sees_nothing(client, admin_token):
    tech = staff_login(client, "tech@demo.example")
    p = new_patient(client, tech)
    lesion = new_lesion(client, tech, p["id"])
    visit = new_visit(client, tech, lesion["id"], "2026-01-08")
    file_id = upload(client, tech, visit["id"], [("a.jpg", unique_scan())]).json()[0]["file_id"]
    _, other = second_hospital(client, admin_token)

    for method, path in (("get", f"/patients/{p['id']}"), ("get", f"/patients/{p['id']}/lesions"),
                         ("get", f"/lesions/{lesion['id']}/timeline"), ("get", f"/files/{file_id}/content"),
                         ("get", f"/files/{file_id}/thumbnail"), ("post", f"/patients/{p['id']}/invite")):
        r = getattr(client, method)(f"{API}{path}", headers=auth(other))
        assert r.status_code == 404, (path, r.status_code)
    r = upload(client, other, visit["id"], [("b.jpg", unique_scan())])
    assert r.status_code == 404
    assert p["id"] not in [i["id"] for i in client.get(f"{API}/patients", headers=auth(other)).json()["items"]]


def test_patients_cannot_use_staff_record_endpoints(client):
    patient = patient_login(client)
    assert client.get(f"{API}/patients", headers=auth(patient)).status_code == 403
    me = client.get(f"{API}/auth/me", headers=auth(patient)).json()
    assert client.get(f"{API}/patients/{me['patient_id']}", headers=auth(patient)).status_code == 403
    lesion_id = client.get(f"{API}/me/lesions", headers=auth(patient)).json()[0]["id"]
    assert client.get(f"{API}/lesions/{lesion_id}/timeline", headers=auth(patient)).status_code == 403
