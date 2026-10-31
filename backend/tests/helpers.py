import io
import itertools
import os

import numpy as np
import psycopg

from app.scripts.synthetic import lesion_image, simple_pdf
from tests.conftest import API, auth

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
