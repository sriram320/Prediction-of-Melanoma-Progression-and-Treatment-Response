"""P2: encryption at rest, file access rules, audit, documents and the patient portal."""
import hashlib
import os
from pathlib import Path

from tests.conftest import API, auth, patient_login, staff_login
from tests.helpers import db_conn, new_lesion, new_patient, new_visit, unique_pdf, unique_scan, upload


def _stored(file_id: str) -> tuple[Path, str]:
    with db_conn() as conn:
        rel, digest = conn.execute("SELECT storage_path, sha256 FROM stored_files WHERE id = %s", (file_id,)).fetchone()
    return Path(os.environ["STORAGE_ROOT"]) / rel, digest


def _scan_file(client, token) -> str:
    p = new_patient(client, token)
    visit = new_visit(client, token, new_lesion(client, token, p["id"])["id"], "2026-02-02")
    return upload(client, token, visit["id"], [("scan.jpg", unique_scan())]).json()[0]["file_id"]


def test_files_are_encrypted_at_rest_and_audited(client):
    tech = staff_login(client, "tech@demo.example")
    file_id = _scan_file(client, tech)
    path, digest = _stored(file_id)
    on_disk = path.read_bytes()
    assert not on_disk.startswith(b"\xff\xd8\xff") and b"JFIF" not in on_disk

    r = client.get(f"{API}/files/{file_id}/content", headers=auth(tech))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert hashlib.sha256(r.content).hexdigest() == digest
    assert r.headers["cache-control"] == "private, no-store" and "inline" in r.headers["content-disposition"]
    assert "attachment" in client.get(f"{API}/files/{file_id}/content?download=true",
                                      headers=auth(tech)).headers["content-disposition"]

    thumb = client.get(f"{API}/files/{file_id}/thumbnail?size=128", headers=auth(tech))
    assert thumb.status_code == 200 and thumb.content[:3] == b"\xff\xd8\xff"
    assert client.get(f"{API}/files/{file_id}/thumbnail?size=999", headers=auth(tech)).status_code == 422
    with db_conn() as conn:
        variants = [row[0] for row in conn.execute(
            "SELECT details->>'variant' FROM audit_log WHERE action = 'file.read' AND entity_id = %s", (file_id,))]
    assert variants.count("original") == 2 and "thumbnail_128" in variants


def test_tampered_ciphertext_is_refused(client):
    tech = staff_login(client, "tech@demo.example")
    file_id = _scan_file(client, tech)
    path, _ = _stored(file_id)
    data = bytearray(path.read_bytes())
    data[100] ^= 0xFF
    path.write_bytes(bytes(data))
    r = client.get(f"{API}/files/{file_id}/content", headers=auth(tech))
    assert r.status_code == 500 and r.json()["code"] == "FILE_UNAVAILABLE"


def test_document_sharing_controls_patient_access(client):
    tech = staff_login(client, "tech@demo.example")
    doctor = staff_login(client, "doctor@demo.example")
    patient = patient_login(client)
    patient_id = client.get(f"{API}/auth/me", headers=auth(patient)).json()["patient_id"]
    pdf = unique_pdf("Histopathology")

    form = {"category": "histopathology", "title": "Excision biopsy", "document_date": "2026-02-10"}
    r = client.post(f"{API}/patients/{patient_id}/documents", headers=auth(tech),
                    data={**form, "visible_to_patient": "true"}, files={"file": ("bx.pdf", pdf, "application/pdf")})
    assert r.status_code == 403  # technicians cannot share with the patient
    r = client.post(f"{API}/patients/{patient_id}/documents", headers=auth(tech), data=form,
                    files={"file": ("bx.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["visible_to_patient"] is False and doc["uploaded_by_name"] == "Ravi Kumar"
    dup = client.post(f"{API}/patients/{patient_id}/documents", headers=auth(tech), data=form,
                      files={"file": ("again.pdf", pdf, "application/pdf")})
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_DOCUMENT"
    bad = client.post(f"{API}/patients/{patient_id}/documents", headers=auth(tech), data=form,
                      files={"file": ("x.exe", b"MZ\x90\x00binary", "application/pdf")})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_FILE"

    titles = lambda: [d["title"] for d in client.get(f"{API}/me/documents", headers=auth(patient)).json()]  # noqa: E731
    assert "Excision biopsy" not in titles()
    assert client.get(f"{API}/files/{doc['file_id']}/content", headers=auth(patient)).status_code == 404

    assert client.patch(f"{API}/documents/{doc['id']}", headers=auth(tech),
                        json={"visible_to_patient": True}).status_code == 403
    r = client.patch(f"{API}/documents/{doc['id']}", headers=auth(doctor), json={"visible_to_patient": True})
    assert r.status_code == 200 and r.json()["visible_to_patient"] is True
    assert "Excision biopsy" in titles()
    r = client.get(f"{API}/files/{doc['file_id']}/content", headers=auth(patient))
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")

    client.patch(f"{API}/documents/{doc['id']}", headers=auth(doctor), json={"visible_to_patient": False})
    assert client.get(f"{API}/files/{doc['file_id']}/content", headers=auth(patient)).status_code == 404


def test_patient_portal_shows_own_scans_without_ai_results(client):
    patient = patient_login(client)
    overview = client.get(f"{API}/me/overview", headers=auth(patient)).json()
    assert overview["lesion_count"] == 1 and overview["visit_count"] == 3 and overview["hospital_name"]

    lesions = client.get(f"{API}/me/lesions", headers=auth(patient)).json()
    assert len(lesions) == 1 and len(lesions[0]["visits"]) == 3
    flat = str(lesions)
    for hidden in ("risk", "prediction", "quality", "notes"):
        assert hidden not in flat
    file_id = lesions[0]["visits"][0]["images"][0]["file_id"]
    assert client.get(f"{API}/files/{file_id}/thumbnail", headers=auth(patient)).status_code == 200
    seeded = [d["title"] for d in client.get(f"{API}/me/documents", headers=auth(patient)).json()]
    assert "Visit summary (demo)" in seeded and "Blood test results (demo)" not in seeded

    for path in ("/me/overview", "/me/lesions", "/me/documents"):
        assert client.get(f"{API}{path}", headers=auth(staff_login(client, "doctor@demo.example"))).status_code == 403


def test_patient_cannot_read_another_patients_files(client):
    tech = staff_login(client, "tech@demo.example")
    other_file = _scan_file(client, tech)
    patient = patient_login(client)
    assert client.get(f"{API}/files/{other_file}/content", headers=auth(patient)).status_code == 404
    assert client.get(f"{API}/files/{other_file}/thumbnail", headers=auth(patient)).status_code == 404


def test_patient_activated_via_invite_sees_their_baseline_scan(client):
    """Demo patient 2 has one seeded visit and activates with the demo invite code."""
    r = client.post(f"{API}/auth/patient/activate", json={
        "invite_code": "DEMO-INVITE-2026", "date_of_birth": "1988-11-02", "phone": "+919800000077",
        "password": "Patient2pass"})
    if r.status_code == 400:  # already activated by test_auth in this session
        token = patient_login(client, "+919800000002", "Patient2pass")
    else:
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
    lesions = client.get(f"{API}/me/lesions", headers=auth(token)).json()
    assert len(lesions) == 1 and len(lesions[0]["visits"]) == 1
    assert client.get(f"{API}/me/documents", headers=auth(token)).json() == []
