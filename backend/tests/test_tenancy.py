"""Role checks and hospital scoping (invariant 5): other hospitals' resources look like 404."""
from tests.conftest import DEMO_PASSWORD, auth, staff_login

API = "/api/v1"


def _second_hospital(client, admin_token) -> tuple[str, str]:
    """Creates hospital SECOND (once) with an admin; returns (hospital_id, admin access token)."""
    r = client.get(f"{API}/admin/hospitals?q=SECOND", headers=auth(admin_token))
    if r.json()["total"] == 0:
        r = client.post(f"{API}/admin/hospitals", headers=auth(admin_token),
                        json={"code": "second", "name": "Second Hospital", "contact_phone": "+91 80 1234 5678"})
        assert r.status_code == 201, r.text
        hid = r.json()["id"]
        r = client.post(f"{API}/admin/hospitals/{hid}/admins", headers=auth(admin_token),
                        json={"full_name": "Second Admin", "email": "admin2@second.example"})
        assert r.status_code == 201, r.text
        temp = r.json()["temp_password"]
        login = client.post(f"{API}/auth/hospital/login",
                            json={"hospital_code": "SECOND", "email": "admin2@second.example", "password": temp})
        tok = login.json()["access_token"]
        client.post(f"{API}/auth/change-password", headers=auth(tok),
                    json={"current_password": temp, "new_password": "SecondAdmin123"})
    else:
        hid = r.json()["items"][0]["id"]
    tok = staff_login(client, "admin2@second.example", code="SECOND", password="SecondAdmin123")
    return hid, tok


def test_duplicate_hospital_code_conflicts(client, admin_token):
    r = client.post(f"{API}/admin/hospitals", headers=auth(admin_token), json={"code": "DEMO01", "name": "Dup"})
    assert r.status_code == 409 and r.json()["code"] == "CODE_TAKEN"


def test_staff_roles_enforced(client):
    doctor = staff_login(client, "doctor@demo.example")
    tech = staff_login(client, "tech@demo.example")
    assert client.get(f"{API}/hospital/staff", headers=auth(doctor)).status_code == 403
    assert client.get(f"{API}/hospital/stats", headers=auth(doctor)).status_code == 200
    assert client.get(f"{API}/hospital/stats", headers=auth(tech)).status_code == 403
    assert client.get(f"{API}/admin/hospitals", headers=auth(doctor)).status_code == 403


def test_patient_cannot_reach_staff_endpoints(client):
    r = client.post(f"{API}/auth/patient/login", json={"identifier": "patient@demo.example", "password": DEMO_PASSWORD})
    tok = r.json()["access_token"]
    assert client.get(f"{API}/hospital/stats", headers=auth(tok)).status_code == 403
    assert client.get(f"{API}/hospital/staff", headers=auth(tok)).status_code == 403


def test_hospital_admin_manages_only_own_staff(client, admin_token):
    _, second_admin = _second_hospital(client, admin_token)
    demo_admin = staff_login(client, "admin@demo.example")

    r = client.post(f"{API}/hospital/staff", headers=auth(demo_admin),
                    json={"role": "doctor", "full_name": "Dr. New Hire", "email": "newdoc@demo.example"})
    assert r.status_code == 201, r.text
    new_id = r.json()["user"]["id"]
    assert r.json()["temp_password"]

    dup = client.post(f"{API}/hospital/staff", headers=auth(demo_admin),
                      json={"role": "doctor", "full_name": "Dup", "email": "NEWDOC@demo.example"})
    assert dup.status_code == 409

    # Same email is fine in another hospital (staff emails are unique per hospital).
    other = client.post(f"{API}/hospital/staff", headers=auth(second_admin),
                        json={"role": "technician", "full_name": "Other", "email": "newdoc@demo.example"})
    assert other.status_code == 201

    # Second hospital's admin cannot see or modify DEMO01 staff: 404, not 403.
    r = client.patch(f"{API}/hospital/staff/{new_id}", headers=auth(second_admin), json={"is_active": False})
    assert r.status_code == 404
    names = [s["email"] for s in client.get(f"{API}/hospital/staff", headers=auth(second_admin)).json()["items"]]
    assert "doctor@demo.example" not in names

    r = client.patch(f"{API}/hospital/staff/{new_id}", headers=auth(demo_admin),
                     json={"is_active": False, "reset_password": True})
    assert r.status_code == 200
    assert r.json()["user"]["is_active"] is False and r.json()["temp_password"]


def test_admin_cannot_deactivate_self(client):
    demo_admin = staff_login(client, "admin@demo.example")
    me = client.get(f"{API}/auth/me", headers=auth(demo_admin)).json()
    r = client.patch(f"{API}/hospital/staff/{me['id']}", headers=auth(demo_admin), json={"is_active": False})
    assert r.status_code == 400


def test_inactive_hospital_blocks_login_and_tokens(client, admin_token):
    hid, second_admin = _second_hospital(client, admin_token)
    r = client.patch(f"{API}/admin/hospitals/{hid}", headers=auth(admin_token), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    try:
        r = client.get(f"{API}/hospital/staff", headers=auth(second_admin))
        assert r.status_code == 403 and r.json()["code"] == "HOSPITAL_INACTIVE"
        r = client.post(f"{API}/auth/hospital/login",
                        json={"hospital_code": "SECOND", "email": "admin2@second.example", "password": "SecondAdmin123"})
        assert r.status_code == 403 and r.json()["code"] == "HOSPITAL_INACTIVE"
    finally:
        client.patch(f"{API}/admin/hospitals/{hid}", headers=auth(admin_token), json={"is_active": True})


def test_hospital_detail_lists_admins(client, admin_token):
    hid = client.get(f"{API}/admin/hospitals?q=DEMO01", headers=auth(admin_token)).json()["items"][0]["id"]
    r = client.get(f"{API}/admin/hospitals/{hid}", headers=auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["staff_count"] >= 3 and body["patient_count"] == 2
    assert any(a["email"] == "admin@demo.example" for a in body["admins"])
