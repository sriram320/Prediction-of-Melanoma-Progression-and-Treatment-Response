import psycopg
import pytest

from tests.conftest import DEMO_PASSWORD, auth, staff_login

API = "/api/v1"


def test_health_is_public_and_reports_mock_model(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["model"]["is_mock"] is True
    assert body["ml_service"] == "unavailable"


def test_temporary_password_must_be_changed_first(client):
    demo_admin = staff_login(client, "admin@demo.example")
    r = client.post(f"{API}/hospital/staff", headers=auth(demo_admin),
                    json={"role": "technician", "full_name": "First Login", "email": "firstlogin@demo.example"})
    temp = r.json()["temp_password"]
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": "DEMO01", "email": "firstlogin@demo.example", "password": temp})
    token = r.json()["access_token"]
    assert r.json()["user"]["must_change_password"] is True
    r = client.get(f"{API}/patients", headers=auth(token))
    assert r.status_code == 403 and r.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get(f"{API}/auth/me", headers=auth(token)).status_code == 200
    r = client.post(f"{API}/auth/change-password", headers=auth(token),
                    json={"current_password": temp, "new_password": "FirstLogin2026"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert client.get(f"{API}/patients", headers=auth(token)).status_code == 200


def test_hospital_login_sets_refresh_cookie_and_me(client):
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": "demo01", "email": "doctor@demo.example", "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    assert "mt_refresh" in r.cookies
    me = r.json()["user"]
    assert me["role"] == "doctor" and me["hospital"]["code"] == "DEMO01"
    assert "password_hash" not in r.text


def test_wrong_hospital_code_or_password_is_generic(client):
    for code, pw in (("NOPE99", DEMO_PASSWORD), ("DEMO01", "wrong-password1")):
        r = client.post(f"{API}/auth/hospital/login",
                        json={"hospital_code": code, "email": "tech@demo.example", "password": pw})
        assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"


def test_patient_cannot_use_hospital_login(client):
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": "DEMO01", "email": "patient@demo.example", "password": DEMO_PASSWORD})
    assert r.status_code == 401


def test_patient_login_by_email_or_phone(client):
    for ident in ("patient@demo.example", "+91 98000 00001"):
        r = client.post(f"{API}/auth/patient/login", json={"identifier": ident, "password": DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "patient"
        assert r.json()["user"]["patient_id"]


def test_refresh_rotates_and_detects_reuse(client):
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": "DEMO01", "email": "tech@demo.example", "password": DEMO_PASSWORD})
    first = r.cookies["mt_refresh"]
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 200, r.text
    second = r.cookies["mt_refresh"]
    assert second != first

    client.cookies.set("mt_refresh", first, path="/api/v1/auth")  # replay the rotated token
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_REUSED"

    client.cookies.set("mt_refresh", second, path="/api/v1/auth")  # the whole family is now revoked
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_concurrent_refresh_within_grace_is_retryable(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "refresh_reuse_grace_s", 30)
    client.post(f"{API}/auth/hospital/login",
                json={"hospital_code": "DEMO01", "email": "doctor@demo.example", "password": DEMO_PASSWORD})
    first = client.cookies["mt_refresh"]
    assert client.post(f"{API}/auth/refresh").status_code == 200
    second = client.cookies["mt_refresh"]

    client.cookies.set("mt_refresh", first, path="/api/v1/auth")  # the "other tab" lost the race
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_RACE"

    client.cookies.set("mt_refresh", second, path="/api/v1/auth")  # its retry with the new cookie works
    assert client.post(f"{API}/auth/refresh").status_code == 200


def test_logout_revokes_session(client):
    client.post(f"{API}/auth/patient/login", json={"identifier": "patient@demo.example", "password": DEMO_PASSWORD})
    token = client.cookies["mt_refresh"]
    assert client.post(f"{API}/auth/logout").status_code == 204
    client.cookies.set("mt_refresh", token, path="/api/v1/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_lockout_after_five_failures(client, admin_token):
    hid = client.get(f"{API}/admin/hospitals?q=DEMO01", headers=auth(admin_token)).json()["items"][0]["id"]
    r = client.post(f"{API}/admin/hospitals/{hid}/admins", headers=auth(admin_token),
                    json={"full_name": "Lock Test", "email": "locktest@demo.example"})
    temp = r.json()["temp_password"]
    for _ in range(5):
        r = client.post(f"{API}/auth/hospital/login",
                        json={"hospital_code": "DEMO01", "email": "locktest@demo.example", "password": "bad-pass-123"})
        assert r.status_code == 401
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": "DEMO01", "email": "locktest@demo.example", "password": temp})
    assert r.status_code == 423 and r.json()["code"] == "ACCOUNT_LOCKED"


def test_patient_activation_with_invite(client):
    bad = client.post(f"{API}/auth/patient/activate", json={
        "invite_code": "demo-invite-2026", "date_of_birth": "1990-01-01", "phone": "+919800000099",
        "password": "Patient2pass"})
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_INVITE"

    weak = client.post(f"{API}/auth/patient/activate", json={
        "invite_code": "DEMO-INVITE-2026", "date_of_birth": "1988-11-02", "phone": "+919800000002",
        "password": "short"})
    assert weak.status_code == 422

    ok = client.post(f"{API}/auth/patient/activate", json={
        "invite_code": "DEMO-INVITE-2026", "date_of_birth": "1988-11-02", "phone": "+919800000002",
        "password": "Patient2pass"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["user"]["role"] == "patient"

    again = client.post(f"{API}/auth/patient/activate", json={
        "invite_code": "DEMO-INVITE-2026", "date_of_birth": "1988-11-02", "phone": "+919800000003",
        "password": "Patient2pass"})
    assert again.status_code == 400  # invite already used

    r = client.post(f"{API}/auth/patient/login", json={"identifier": "+919800000002", "password": "Patient2pass"})
    assert r.status_code == 200


def test_change_password_rules(client):
    token = staff_login(client, "tech@demo.example")
    r = client.post(f"{API}/auth/change-password", headers=auth(token),
                    json={"current_password": "wrong", "new_password": "Something123"})
    assert r.status_code == 400 and r.json()["code"] == "WRONG_PASSWORD"
    r = client.post(f"{API}/auth/change-password", headers=auth(token),
                    json={"current_password": DEMO_PASSWORD, "new_password": "allletters"})
    assert r.status_code == 422


def test_audit_log_is_append_only_and_chained(client):
    import os
    staff_login(client, "doctor@demo.example")
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT prev_hash, row_hash FROM audit_log ORDER BY id DESC LIMIT 2").fetchall()
        assert rows[0][1] and rows[0][0] == rows[1][1]
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE audit_log SET action = 'x'")
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM audit_log")
