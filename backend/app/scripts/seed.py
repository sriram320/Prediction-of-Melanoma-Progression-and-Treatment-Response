"""Idempotent seed: super admin, the mock model version and (SEED_DEMO=true) a demo hospital.

Run: `python -m app.scripts.seed`. Safe to run on every start; existing rows are left unchanged.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password, normalize_invite_code, sha256_hex
from app.models import (Document, Hospital, Image, Lesion, ModelVersion, Patient, PatientIdentity, PatientInvite,
                        User, Visit)
from app.scripts import synthetic
from app.services import files as files_svc
from app.services import imaging
from app.services.patients import age_band, new_pseudonym

log = logging.getLogger("seed")

DEMO_HOSPITAL_CODE = "DEMO01"
DEMO_INVITE_CODE = "DEMO-INVITE-2026"  # dev only; patient 2 activates with this and DOB 1988-11-02
DEMO_STAFF = [
    ("hospital_admin", "Asha Menon", "admin@demo.example", None),
    ("doctor", "Dr. Kiran Rao", "doctor@demo.example", "KMC-45120"),
    ("technician", "Ravi Kumar", "tech@demo.example", None),
]


async def seed_super_admin(db: AsyncSession) -> None:
    email = settings.seed_superadmin_email
    if await db.scalar(select(User).where(User.role == "super_admin", User.email == email)):
        return
    db.add(User(role="super_admin", email=email, full_name="Platform Administrator",
                password_hash=hash_password(settings.seed_superadmin_password), must_change_password=True))
    log.info("Created super admin %s (must change password at first login)", email)


async def seed_mock_model(db: AsyncSession) -> None:
    if await db.scalar(select(ModelVersion).where(ModelVersion.name == "mock", ModelVersion.version == "0.1.0")):
        return
    has_active = await db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    db.add(ModelVersion(name="mock", version="0.1.0", adapter="mock", is_mock=True, is_active=has_active is None,
                        model_card="Deterministic mock for UI development. NOT FOR CLINICAL USE.",
                        metrics={}))
    log.info("Registered mock model 0.1.0")


async def seed_demo(db: AsyncSession) -> None:
    hospital = await db.scalar(select(Hospital).where(Hospital.code == DEMO_HOSPITAL_CODE))
    if hospital is not None:
        return
    hospital = Hospital(code=DEMO_HOSPITAL_CODE, name="MelanoTrack Demo Hospital",
                        address="Demo Campus, Bengaluru", contact_email="contact@demo.example")
    db.add(hospital)
    await db.flush()

    pw = hash_password(settings.seed_demo_password)
    staff = {}
    for role, name, email, reg in DEMO_STAFF:
        u = User(hospital_id=hospital.id, role=role, full_name=name, email=email, registration_no=reg,
                 password_hash=pw, must_change_password=False)
        db.add(u)
        staff[role] = u
    await db.flush()

    # Patient 1 already has a login; patient 2 is waiting to be activated with the demo invite code.
    p1_dob, p2_dob = date(1975, 4, 18), date(1988, 11, 2)
    p1 = Patient(hospital_id=hospital.id, mrn="DEMO-0001", pseudonym_id=new_pseudonym(), sex="female",
                 age_band=age_band(p1_dob), fitzpatrick_type=4, consent_status=True,
                 consent_at=datetime.now(timezone.utc), created_by=staff["technician"].id)
    p2 = Patient(hospital_id=hospital.id, mrn="DEMO-0002", pseudonym_id=new_pseudonym(), sex="male",
                 age_band=age_band(p2_dob), fitzpatrick_type=5, consent_status=True,
                 consent_at=datetime.now(timezone.utc), created_by=staff["technician"].id)
    db.add_all([p1, p2])
    await db.flush()
    db.add_all([
        PatientIdentity(patient_id=p1.id, full_name="Lakshmi Iyer", date_of_birth=p1_dob,
                        email="patient@demo.example", phone="+919800000001"),
        PatientIdentity(patient_id=p2.id, full_name="Arjun Shetty", date_of_birth=p2_dob, phone="+919800000002"),
    ])
    p1_user = User(hospital_id=hospital.id, role="patient", full_name="Lakshmi Iyer", email="patient@demo.example",
                   phone="+919800000001", password_hash=pw, must_change_password=False)
    db.add(p1_user)
    await db.flush()
    p1.user_id = p1_user.id
    db.add(PatientInvite(patient_id=p2.id, code_hash=sha256_hex(normalize_invite_code(DEMO_INVITE_CODE)),
                         expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                         created_by=staff["technician"].id))
    log.info("Created demo hospital %s with staff, 2 patients and invite code %s",
             DEMO_HOSPITAL_CODE, DEMO_INVITE_CODE)


async def _demo_scan(db: AsyncSession, visit: Visit, tech: User, index: int, seed: int) -> None:
    raw = synthetic.lesion_image(index, seed=seed)
    prepared = imaging.prepare_scan(raw, imaging.JPEG)
    stored, _ = await files_svc.store(db, hospital_id=visit.hospital_id, data=prepared.data, mime=prepared.mime,
                                      filename=f"synthetic_visit_{index + 1}.jpg", uploaded_by=tech.id)
    db.add(Image(visit_id=visit.id, hospital_id=visit.hospital_id, modality="dermoscopic", file_id=stored.id,
                 width=prepared.width, height=prepared.height, quality_score=prepared.quality_score,
                 quality_flags=prepared.quality_flags))
    visit.quality_score, visit.quality_flags = prepared.quality_score, prepared.quality_flags


async def _demo_lesion(db: AsyncSession, patient: Patient, tech: User, label: str, site: str,
                       days_ago: list[int], seed: int) -> Lesion:
    lesion = Lesion(patient_id=patient.id, hospital_id=patient.hospital_id, label=label, anatomical_site=site)
    db.add(lesion)
    await db.flush()
    for index, ago in enumerate(days_ago):
        visit = Visit(lesion_id=lesion.id, hospital_id=patient.hospital_id,
                      visit_date=date.today() - timedelta(days=ago), device_model="DermLite DL4 (synthetic)",
                      polarised=True, notes="Synthetic demo image, not a real patient.", created_by=tech.id)
        db.add(visit)
        await db.flush()
        if index == 0:
            lesion.first_seen_visit_id = visit.id
        await _demo_scan(db, visit, tech, index, seed)
    return lesion


async def seed_demo_records(db: AsyncSession) -> None:
    """Synthetic lesions and documents for the demo patients, added once (also to an existing demo hospital)."""
    hospital = await db.scalar(select(Hospital).where(Hospital.code == DEMO_HOSPITAL_CODE))
    if hospital is None:
        return
    patients = {p.mrn: p for p in (await db.scalars(select(Patient).where(Patient.hospital_id == hospital.id))).all()}
    tech = await db.scalar(select(User).where(User.hospital_id == hospital.id, User.role == "technician"))
    p1, p2 = patients.get("DEMO-0001"), patients.get("DEMO-0002")
    if p1 is None or p2 is None or tech is None:
        return
    if await db.scalar(select(Lesion.id).where(Lesion.patient_id.in_([p1.id, p2.id])).limit(1)) is not None:
        return

    await _demo_lesion(db, p1, tech, "L1 - left shoulder", "posterior_torso", [365, 180, 21], seed=7)
    await _demo_lesion(db, p2, tech, "L1 - right forearm", "upper_extremity", [14], seed=19)
    for title, category, visible in (("Visit summary (demo)", "discharge_summary", True),
                                     ("Blood test results (demo)", "lab_report", False)):
        pdf = synthetic.simple_pdf(title, ["MelanoTrack demo document.", "Synthetic content, not a real patient.",
                                           f"Patient record: {p1.mrn}"])
        stored, _ = await files_svc.store(db, hospital_id=hospital.id, data=pdf, mime=imaging.PDF,
                                          filename=f"{category}.pdf", uploaded_by=tech.id)
        db.add(Document(patient_id=p1.id, hospital_id=hospital.id, file_id=stored.id, category=category, title=title,
                        document_date=date.today() - timedelta(days=21), visible_to_patient=visible,
                        uploaded_by=tech.id))
    log.info("Added synthetic demo lesions (3 visits and 1 visit) and 2 documents to %s", DEMO_HOSPITAL_CODE)


async def run() -> None:
    async with SessionLocal() as db:
        await seed_super_admin(db)
        await seed_mock_model(db)
        if settings.seed_demo:
            await seed_demo(db)
            await db.flush()
            await seed_demo_records(db)
        await db.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())
