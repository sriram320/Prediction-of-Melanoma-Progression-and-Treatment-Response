"""Idempotent seed: super admin, the mock model version and (SEED_DEMO=true) a demo hospital.

Run: `python -m app.scripts.seed`. Safe to run on every start; existing rows are left unchanged.
"""
import asyncio
import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password, normalize_invite_code, sha256_hex
from app.models import Hospital, ModelVersion, Patient, PatientIdentity, PatientInvite, User

log = logging.getLogger("seed")

DEMO_HOSPITAL_CODE = "DEMO01"
DEMO_INVITE_CODE = "DEMO-INVITE-2026"  # dev only; patient 2 activates with this and DOB 1988-11-02
DEMO_STAFF = [
    ("hospital_admin", "Asha Menon", "admin@demo.example", None),
    ("doctor", "Dr. Kiran Rao", "doctor@demo.example", "KMC-45120"),
    ("technician", "Ravi Kumar", "tech@demo.example", None),
]


def age_band(dob: date, today: date | None = None) -> str:
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years >= 90:
        return "90+"
    lo = (years // 10) * 10
    return f"{lo}-{lo + 9}"


def new_pseudonym() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "MT-" + "".join(secrets.choice(alphabet) for _ in range(8))


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


async def run() -> None:
    async with SessionLocal() as db:
        await seed_super_admin(db)
        await seed_mock_model(db)
        if settings.seed_demo:
            await seed_demo(db)
        await db.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())
