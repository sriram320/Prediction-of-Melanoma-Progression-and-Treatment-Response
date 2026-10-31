import io
import itertools
import os

import numpy as np
import psycopg

from app.scripts.synthetic import lesion_image, simple_pdf
from tests.conftest import API, auth, staff_login

_counter = itertools.count(1000)  # unique synthetic seeds: identical bytes would be de-duplicated per hospital


def db_conn():
    return psycopg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def unique_scan(visit_index: int = 0) -> bytes:
    return lesion_image(visit_index, width=800, height=640, seed=next(_counter))


def unique_pdf(title: str = "Report") -> bytes:
    return simple_pdf(title, [f"Synthetic test document {next(_counter)}"])


def new_patient(client, token, **overrides) -> dict:
    n = next(_counter)
    body = {"mrn": f"T-{n}", "full_name": f"Test Patient {n}", "date_of_birth": "1980-05-17", "sex": "female",
            "fitzpatrick_type": 3, "consent_status": True, **overrides}
    r = client.post(f"{API}/patients", headers=auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def new_lesion(client, token, patient_id, label="L1 - back", site="posterior_torso") -> dict:
    r = client.post(f"{API}/patients/{patient_id}/lesions", headers=auth(token),
                    json={"label": label, "anatomical_site": site})
    assert r.status_code == 201, r.text
    return r.json()


def new_visit(client, token, lesion_id, visit_date="2026-01-10", **extra) -> dict:
    r = client.post(f"{API}/lesions/{lesion_id}/visits", headers=auth(token), json={"visit_date": visit_date, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, token, visit_id, files: list[tuple[str, bytes]], modality="dermoscopic"):
    return client.post(f"{API}/visits/{visit_id}/images", headers=auth(token), data={"modality": modality},
                       files=[("files", (name, data, "application/octet-stream")) for name, data in files])


def dicom_bytes(model: str = "FotoFinder Medicam 1000") -> bytes:
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = SecondaryCaptureImageStorage, meta.MediaStorageSOPInstanceUID
    ds.PatientName, ds.ManufacturerModelName = "Test^Patient", model
    ds.Rows, ds.Columns, ds.SamplesPerPixel, ds.PhotometricInterpretation = 64, 80, 3, "RGB"
    ds.PlanarConfiguration, ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 0, 8, 8, 7, 0
    ds.PixelData = np.random.default_rng(next(_counter)).integers(0, 255, (64, 80, 3), dtype=np.uint8).tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def run_worker() -> int:
    """Processes every queued analysis job; returns how many ran."""
    import asyncio

    from app.workers.inference_worker import process_once

    async def drain() -> int:
        n = 0
        while await process_once():
            n += 1
        return n

    return asyncio.run(drain())


def lesion_with_visits(client, token, n_visits: int, **patient):
    p = new_patient(client, token, **patient)
    lesion = new_lesion(client, token, p["id"])
    visits = []
    for i in range(n_visits):
        visit = new_visit(client, token, lesion["id"], f"2025-{2 + 4 * i:02d}-10")
        assert upload(client, token, visit["id"], [(f"v{i}.jpg", unique_scan(i))]).json()[0]["image_id"]
        visits.append(visit)
    return p, lesion, visits


def analyse(client, token, lesion_id, **body) -> str:
    r = client.post(f"{API}/lesions/{lesion_id}/analyze", headers=auth(token), json=body or None)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


FRESH_PASSWORD = "FreshPass123!"


def _first_login(client, code: str, email: str, temp_password: str) -> str:
    r = client.post(f"{API}/auth/hospital/login",
                    json={"hospital_code": code, "email": email, "password": temp_password})
    assert r.status_code == 200, r.text
    r = client.post(f"{API}/auth/change-password", headers=auth(r.json()["access_token"]),
                    json={"current_password": temp_password, "new_password": FRESH_PASSWORD})
    assert r.status_code == 200, r.text
    return staff_login(client, email, code=code, password=FRESH_PASSWORD)


def fresh_hospital(client, admin_token) -> dict:
    """A new, empty hospital with an admin, a doctor and a technician, for tests that count things.
    Returns {"id", "code", "admin", "doctor", "tech"} (the last three are access tokens)."""
    code = f"FH{next(_counter)}"
    r = client.post(f"{API}/admin/hospitals", headers=auth(admin_token), json={"code": code, "name": f"Hospital {code}"})
    assert r.status_code == 201, r.text
    out = {"id": r.json()["id"], "code": code}
    email = f"admin@{code.lower()}.example"
    r = client.post(f"{API}/admin/hospitals/{out['id']}/admins", headers=auth(admin_token),
                    json={"full_name": f"Admin {code}", "email": email})
    assert r.status_code == 201, r.text
    out["admin"] = _first_login(client, code, email, r.json()["temp_password"])
    for role, key in (("doctor", "doctor"), ("technician", "tech")):
        email = f"{key}@{code.lower()}.example"
        r = client.post(f"{API}/hospital/staff", headers=auth(out["admin"]),
                        json={"role": role, "full_name": f"{role.title()} {code}", "email": email})
        assert r.status_code == 201, r.text
        out[key] = _first_login(client, code, email, r.json()["temp_password"])
    return out
