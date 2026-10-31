"""P5: risk trend, hospital activity, the subgroup fairness report (S1) and the audit log viewer (S3)."""
import json
from datetime import date, timedelta

from tests.conftest import API, auth, patient_login, staff_login
from tests.helpers import (analyse, db_conn, fresh_hospital, new_lesion, new_patient, new_visit, run_worker,
                           unique_scan, upload)

CATEGORIES = ("routine_monitoring", "shortened_interval", "specialist_referral")


def _lesion(client, tech, *, fitzpatrick, device="DermLite DL4", illumination="polarised", visits=2,
            site="posterior_torso"):
    p = new_patient(client, tech, fitzpatrick_type=fitzpatrick)
    lesion = new_lesion(client, tech, p["id"], site=site)
    for i in range(visits):
        v = new_visit(client, tech, lesion["id"], f"2025-{2 + 4 * i:02d}-10", device_model=device,
                      illumination=illumination)
        assert upload(client, tech, v["id"], [(f"v{i}.jpg", unique_scan(i))]).json()[0]["image_id"]
    return p, lesion


def _analysed(client, tech, doctor, **kw):
    p, lesion = _lesion(client, tech, **kw)
    analyse(client, tech, lesion["id"])
    run_worker()
    pred = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(doctor)).json()["latest_prediction"]
    return p, lesion, pred


def _review(client, doctor, pred, category, reason=None):
    r = client.post(f"{API}/predictions/{pred['id']}/review", headers=auth(doctor),
                    json={"final_category": category, "reason": reason})
    assert r.status_code == 201, r.text


def _biopsy(client, doctor, lesion_id, result, kind="punch_biopsy"):
    r = client.post(f"{API}/lesions/{lesion_id}/treatment-events", headers=auth(doctor),
                    json={"treatment_type": kind, "treatment_date": "2025-12-01", "histopathology": result})
    assert r.status_code == 201, r.text
    return r.json()


def _report(client, token, **params):
    return client.get(f"{API}/reports/subgroup-performance", headers=auth(token), params=params)


def test_histopathology_result_rules(client, ml):
    tech, doctor = staff_login(client, "tech@demo.example"), staff_login(client, "doctor@demo.example")
    _, lesion = _lesion(client, tech, fitzpatrick=4, visits=1)
    url = f"{API}/lesions/{lesion['id']}/treatment-events"
    r = client.post(url, headers=auth(doctor), json={"treatment_type": "cryotherapy", "treatment_date": "2025-12-01",
                                                     "histopathology": "melanoma"})
    assert r.status_code == 422 and r.json()["code"] == "HISTOPATHOLOGY_NOT_APPLICABLE"

    event = client.post(url, headers=auth(doctor), json={"treatment_type": "excision",
                                                         "treatment_date": "2025-12-01"}).json()
    assert event["histopathology"] is None
    assert client.patch(f"{API}/treatment-events/{event['id']}", headers=auth(tech),
                        json={"histopathology": "melanoma"}).status_code == 403
    r = client.patch(f"{API}/treatment-events/{event['id']}", headers=auth(doctor), json={"histopathology": "melanoma"})
    assert r.status_code == 200 and r.json()["histopathology"] == "melanoma" and r.json()["histopathology_recorded_at"]
    timeline = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(tech)).json()
    assert timeline["treatment_events"][0]["histopathology"] == "melanoma"
    with db_conn() as conn:
        details = conn.execute("SELECT details FROM audit_log WHERE action = 'treatment.update' AND entity_id = %s",
                               (event["id"],)).fetchone()[0]
    assert details["fields"] == ["histopathology"] and "melanoma" not in json.dumps(details)
    r = client.patch(f"{API}/treatment-events/00000000-0000-4000-8000-000000000000", headers=auth(doctor),
                     json={"histopathology": None})
    assert r.status_code == 404


def test_subgroup_report(client, ml, monkeypatch, admin_token):
    h = fresh_hospital(client, admin_token)
    tech, doctor = h["tech"], h["doctor"]
    pa, la, a = _analysed(client, tech, doctor, fitzpatrick=2)
    pb, lb, b = _analysed(client, tech, doctor, fitzpatrick=5, device="Heine Delta 30", site="lower_extremity")
    monkeypatch.setenv("MOCK_FORCE_ERROR", "1")
    pc, lc, c = _analysed(client, tech, doctor, fitzpatrick=5)
    monkeypatch.delenv("MOCK_FORCE_ERROR")
    assert not a["referral_flag"] and not b["referral_flag"] and c["referral_flag"]

    _review(client, doctor, a, a["risk_category"])
    override = next(x for x in CATEGORIES if x != b["risk_category"])
    _review(client, doctor, b, override, "Clinical appearance differs")
    _biopsy(client, doctor, la["id"], "melanoma")
    _biopsy(client, doctor, lb["id"], "not_melanoma", kind="excision")

    r = _report(client, h["admin"])
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["hospital_id"] == h["id"] and rep["any_mock"] is True and rep["min_group_size"] == 10
    o = rep["overall"]
    assert (o["n"], o["referral_n"], o["scored_n"], o["reviewed_scored_n"], o["override_n"]) == (3, 1, 2, 2, 1)
    assert o["referral_rate"] == round(1 / 3, 4) and o["override_rate"] == 0.5 and o["small_sample"] is True
    assert o["mean_risk"] == round((a["risk_score"] + b["risk_score"]) / 2, 4)
    assert (o["outcome_n"], o["melanoma_n"]) == (2, 1)

    flagged = lambda cat: cat in ("shortened_interval", "specialist_referral")  # noqa: E731
    ai = o["ai"]
    assert (ai["tp"], ai["fn"]) == ((1, 0) if flagged(a["risk_category"]) else (0, 1))
    assert (ai["fp"], ai["tn"]) == ((1, 0) if flagged(b["risk_category"]) else (0, 1))
    after = o["after_review"]
    assert (after["fp"], after["tn"]) == ((1, 0) if flagged(override) else (0, 1))
    assert ai["sensitivity"] == (1.0 if flagged(a["risk_category"]) else 0.0)

    dims = {d["key"]: d["rows"] for d in rep["dimensions"]}
    assert set(dims) == {"fitzpatrick_type", "anatomical_site", "device_model", "illumination"}
    skin = {row["value"]: row for row in dims["fitzpatrick_type"]}
    assert [row["value"] for row in dims["fitzpatrick_type"]] == ["2", "5"]
    assert (skin["2"]["n"], skin["5"]["n"], skin["5"]["referral_n"]) == (1, 2, 1)
    devices = [row["value"] for row in dims["device_model"]]
    assert devices == ["DermLite DL4", "Heine Delta 30"]  # most results first
    assert [row["value"] for row in dims["anatomical_site"]] == ["posterior_torso", "lower_extremity"]
    assert sum(b["n"] for b in rep["calibration"]) == 2

    text = r.text
    for patient in (pa, pb, pc):
        assert patient["full_name"] not in text and patient["mrn"] not in text

    # Scoping: hospital staff always get their own hospital; the super admin may pick one or see all.
    demo_admin = staff_login(client, "admin@demo.example")
    mine = _report(client, demo_admin, hospital_id=h["id"]).json()
    assert mine["hospital_id"] != h["id"]
    assert _report(client, admin_token, hospital_id=h["id"]).json()["overall"]["n"] == 3
    platform = _report(client, admin_token).json()
    assert platform["hospital_id"] is None and platform["overall"]["n"] >= 3
    assert _report(client, doctor).status_code == 200
    assert _report(client, tech).status_code == 403
    assert _report(client, patient_login(client)).status_code == 403

    yesterday = (date.today() - timedelta(days=2)).isoformat()
    assert _report(client, h["admin"], to=yesterday).json()["overall"]["n"] == 0
    assert _report(client, h["admin"], **{"from": "2026-02-01", "to": "2026-01-01"}).status_code == 422


def test_risk_trend_and_activity(client, ml, admin_token):
    h = fresh_hospital(client, admin_token)
    tech, doctor = h["tech"], h["doctor"]
    _, lesion, first = _analysed(client, tech, doctor, fitzpatrick=3)
    _review(client, doctor, first, first["risk_category"])
    analyse(client, tech, lesion["id"])
    run_worker()
    _lesion(client, tech, fitzpatrick=3, visits=1)  # active lesion, never analysed

    history = client.get(f"{API}/lesions/{lesion['id']}/predictions", headers=auth(doctor)).json()
    assert len(history) == 2 and history[0]["prediction_id"] == first["id"]
    assert history[0]["final_category"] == first["risk_category"] and history[1]["final_category"] is None
    assert history[0]["model"]["is_mock"] is True
    assert client.get(f"{API}/lesions/{lesion['id']}/predictions", headers=auth(tech)).status_code == 403

    act = client.get(f"{API}/hospital/activity", headers=auth(h["admin"]), params={"months": 6}).json()
    assert len(act["months"]) == 6 and act["months"][-1]["month"] == date.today().strftime("%Y-%m")
    assert act["months"][-1]["analyses"] == 2 and act["months"][-1]["reviews"] == 1
    assert sum(m["visits"] for m in act["months"]) == 0  # visits are dated 2025 (outside the window)
    cur = act["current_results"]
    assert cur["not_analysed"] == 1 and sum(cur[c] for c in CATEGORIES) == 1 and act["awaiting_review"] == 1
    assert act["scored_reviews_90d"] == 1 and act["overrides_90d"] == 0
    assert act["review_median_hours_90d"] is not None and act["review_median_hours_90d"] >= 0
    assert client.get(f"{API}/hospital/activity", headers=auth(doctor)).status_code == 200
    assert client.get(f"{API}/hospital/activity", headers=auth(tech)).status_code == 403


def test_audit_search_is_scoped_and_redacted_for_the_platform(client, ml, admin_token):
    h = fresh_hospital(client, admin_token)
    _, lesion = _lesion(client, h["tech"], fitzpatrick=3, visits=1)
    visit_id = client.get(f"{API}/lesions/{lesion['id']}/timeline", headers=auth(h["doctor"])).json()["visits"][0]["id"]
    r = client.patch(f"{API}/visits/{visit_id}", headers=auth(h["doctor"]),
                     json={"excluded": True, "reason": "Wrong lesion photographed"})
    assert r.status_code == 200, r.text

    page = client.get(f"{API}/audit", headers=auth(h["admin"]), params={"page_size": 200}).json()
    assert page["total"] > 0 and {e["hospital_id"] for e in page["items"]} == {h["id"]}
    exclude = client.get(f"{API}/audit", headers=auth(h["admin"]),
                         params={"action": "visit.exclude", "entity_id": visit_id}).json()["items"]
    assert len(exclude) == 1 and exclude[0]["details"]["reason"] == "Wrong lesion photographed"
    assert exclude[0]["actor_name"] == f"Doctor {h['code']}" and exclude[0]["role"] == "doctor"
    assert exclude[0]["row_hash"] and exclude[0]["hospital_code"] == h["code"]

    group = client.get(f"{API}/audit", headers=auth(h["admin"]), params={"action": "visit"}).json()["items"]
    assert {e["action"] for e in group} == {"visit.create", "visit.exclude"}
    assert client.get(f"{API}/audit", headers=auth(h["admin"]), params={"action": "nope"}).status_code == 422
    assert client.get(f"{API}/audit", headers=auth(h["doctor"])).status_code == 403
    assert "visit.exclude" in client.get(f"{API}/audit/actions", headers=auth(h["admin"])).json()

    platform = client.get(f"{API}/audit", headers=auth(admin_token),
                          params={"action": "visit.exclude", "entity_id": visit_id}).json()["items"]
    assert platform[0]["details"]["reason"] == "[redacted]"
    created = client.get(f"{API}/audit", headers=auth(admin_token), params={"action": "hospital.create"}).json()
    assert len({e["hospital_id"] for e in created["items"]}) > 1
    only = client.get(f"{API}/audit", headers=auth(admin_token), params={"hospital_id": h["id"]}).json()
    assert only["total"] == page["total"]


def test_prediction_trail(client, ml, admin_token):
    h = fresh_hospital(client, admin_token)
    _, lesion, pred = _analysed(client, h["tech"], h["doctor"], fitzpatrick=3)
    _review(client, h["doctor"], pred, pred["risk_category"])
    r = client.post(f"{API}/reports", headers=auth(h["doctor"]), json={"lesion_id": lesion["id"],
                                                                     "prediction_id": pred["id"]})
    assert r.status_code == 201, r.text

    trail = client.get(f"{API}/audit/{pred['id']}", headers=auth(h["doctor"])).json()
    assert [e["action"] for e in trail] == ["job.create", "prediction.create", "prediction.review", "report.create"]
    assert client.get(f"{API}/audit/{pred['id']}", headers=auth(admin_token)).status_code == 200
    demo_admin = staff_login(client, "admin@demo.example")
    assert client.get(f"{API}/audit/{pred['id']}", headers=auth(demo_admin)).status_code == 404
    assert client.get(f"{API}/audit/{pred['id']}", headers=auth(h["tech"])).status_code == 403


def test_hash_chain_verification_detects_tampering(client, admin_token):
    demo_admin = staff_login(client, "admin@demo.example")
    assert client.post(f"{API}/audit/verify", headers=auth(demo_admin)).status_code == 403
    r = client.post(f"{API}/audit/verify", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True and result["checked"] > 0 and result["head_hash"]

    # The test role owns the table, so it can switch the append-only trigger off, like an attacker with DB access.
    def tamper(conn, sql, target):
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_no_update")
        conn.execute(sql, (target,))
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_no_update")
        conn.commit()

    with db_conn() as conn:
        target = conn.execute("SELECT id FROM audit_log ORDER BY id LIMIT 1 OFFSET 5").fetchone()[0]
        tamper(conn, "UPDATE audit_log SET details = details || '{\"tampered\": true}' WHERE id = %s", target)
        try:
            bad = client.post(f"{API}/audit/verify", headers=auth(admin_token)).json()
            assert bad["ok"] is False and bad["hash_mismatches"] == 1 and bad["first_problem_id"] == target
        finally:
            conn.rollback()
            tamper(conn, "UPDATE audit_log SET details = details - 'tampered' WHERE id = %s", target)
    assert client.post(f"{API}/audit/verify", headers=auth(admin_token)).json()["ok"] is True
