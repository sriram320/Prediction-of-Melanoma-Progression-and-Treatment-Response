"""Patient records: registration, search, profile edits and invite codes. Always scoped to the caller's hospital."""
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.core.security import generate_invite_code, normalize_invite_code, sha256_hex
from app.models import Document, Lesion, Patient, PatientIdentity, PatientInvite, User, Visit
from app.schemas.common import Page
from app.schemas.records import (InviteOut, InviteStatus, PatientCreate, PatientListItem, PatientOut,
                                 PatientUpdate)
from app.services.audit import write_audit

PSEUDONYM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def age_band(dob: date, today: date | None = None) -> str:
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years >= 90:
        return "90+"
    lo = max(years, 0) // 10 * 10
    return f"{lo}-{lo + 9}"


def new_pseudonym() -> str:
    return "MT-" + "".join(secrets.choice(PSEUDONYM_ALPHABET) for _ in range(8))


def like_pattern(q: str) -> str:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def patient_in_scope(db: AsyncSession, scope: Scope, patient_id: uuid.UUID) -> Patient:
    patient = await db.get(Patient, patient_id)
    if (patient is None or patient.hospital_id != scope.hospital_id
            or (scope.is_patient and patient.id != scope.patient_id)):
        raise not_found("Patient")
    return patient


async def _pending_invite(db: AsyncSession, patient: Patient) -> InviteStatus | None:
    if patient.user_id is not None:
        return None
    invite = await db.scalar(select(PatientInvite).where(
        PatientInvite.patient_id == patient.id, PatientInvite.used_at.is_(None), PatientInvite.expires_at > _now(),
    ).order_by(PatientInvite.created_at.desc()).limit(1))
    return InviteStatus(expires_at=invite.expires_at, created_at=invite.created_at) if invite else None


async def patient_out(db: AsyncSession, patient: Patient) -> PatientOut:
    ident = patient.identity
    lesions = await db.scalar(select(func.count()).select_from(Lesion).where(Lesion.patient_id == patient.id))
    docs = await db.scalar(select(func.count()).select_from(Document).where(Document.patient_id == patient.id))
    return PatientOut(
        id=patient.id, mrn=patient.mrn, pseudonym_id=patient.pseudonym_id, full_name=ident.full_name,
        date_of_birth=ident.date_of_birth, sex=patient.sex, age_band=age_band(ident.date_of_birth),
        fitzpatrick_type=patient.fitzpatrick_type, phone=ident.phone, email=ident.email, address=ident.address,
        medical_history=patient.medical_history or {}, consent_status=patient.consent_status,
        consent_at=patient.consent_at, has_account=patient.user_id is not None,
        pending_invite=await _pending_invite(db, patient), lesion_count=lesions or 0, document_count=docs or 0,
        created_at=patient.created_at,
    )


async def list_patients(db: AsyncSession, scope: Scope, *, q: str | None, page: int,
                        page_size: int) -> Page[PatientListItem]:
    lesion_count = (select(func.count(Lesion.id)).where(Lesion.patient_id == Patient.id)
                    .correlate(Patient).scalar_subquery())
    last_visit = (select(func.max(Visit.visit_date)).join(Lesion, Visit.lesion_id == Lesion.id)
                  .where(Lesion.patient_id == Patient.id).correlate(Patient).scalar_subquery())
    stmt = (select(Patient.id, Patient.mrn, Patient.pseudonym_id, PatientIdentity.full_name,
                   PatientIdentity.date_of_birth, Patient.sex, Patient.fitzpatrick_type,
                   (Patient.user_id.is_not(None)).label("has_account"), lesion_count.label("lesion_count"),
                   last_visit.label("last_visit_date"), Patient.created_at)
            .join(PatientIdentity, PatientIdentity.patient_id == Patient.id)
            .where(Patient.hospital_id == scope.hospital_id))
    if q and q.strip():
        like = like_pattern(q)
        stmt = stmt.where(or_(PatientIdentity.full_name.ilike(like, escape="\\"), Patient.mrn.ilike(like, escape="\\"),
                              Patient.pseudonym_id.ilike(like, escape="\\")))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(Patient.created_at.desc()).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    items = [PatientListItem(**row._mapping, age_band=age_band(row.date_of_birth)) for row in rows]
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


async def _mrn_taken(db: AsyncSession, hospital_id: uuid.UUID, mrn: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Patient.id).where(Patient.hospital_id == hospital_id, func.lower(Patient.mrn) == mrn.lower())
    if exclude is not None:
        stmt = stmt.where(Patient.id != exclude)
    return await db.scalar(stmt.limit(1)) is not None


MRN_TAKEN = AppError(409, "MRN_TAKEN", "Another patient in this hospital already has this MRN")


async def create_patient(db: AsyncSession, scope: Scope, data: PatientCreate, actor: User,
                         request: Request) -> PatientOut:
    if await _mrn_taken(db, scope.hospital_id, data.mrn):
        raise MRN_TAKEN
    patient = Patient(
        hospital_id=scope.hospital_id, mrn=data.mrn, pseudonym_id=new_pseudonym(), sex=data.sex,
        age_band=age_band(data.date_of_birth), fitzpatrick_type=data.fitzpatrick_type,
        medical_history=data.medical_history.model_dump(exclude_none=True), consent_status=data.consent_status,
        consent_at=_now() if data.consent_status else None, created_by=actor.id,
    )
    patient.identity = PatientIdentity(full_name=data.full_name, date_of_birth=data.date_of_birth,
                                       phone=data.phone, email=data.email, address=data.address)
    db.add(patient)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise MRN_TAKEN
    await write_audit(db, "patient.create", user=actor, entity_type="patient", entity_id=patient.id,
                      details={"consent": data.consent_status}, request=request)
    await db.commit()
    return await patient_out(db, patient)


async def get_patient(db: AsyncSession, scope: Scope, patient_id: uuid.UUID) -> PatientOut:
    return await patient_out(db, await patient_in_scope(db, scope, patient_id))


IDENTITY_FIELDS = ("full_name", "date_of_birth", "phone", "email", "address")
CLINICAL_FIELDS = ("mrn", "sex", "fitzpatrick_type", "consent_status")


async def update_patient(db: AsyncSession, scope: Scope, patient_id: uuid.UUID, data: PatientUpdate, actor: User,
                         request: Request) -> PatientOut:
    patient = await patient_in_scope(db, scope, patient_id)
    ident = patient.identity
    sent = data.model_fields_set
    changed: list[str] = []
    required = {"full_name", "date_of_birth", "mrn", "sex", "consent_status"}

    for name in IDENTITY_FIELDS:
        value = getattr(data, name)
        if name in sent and not (value is None and name in required) and getattr(ident, name) != value:
            setattr(ident, name, value)
            changed.append(name)
    for name in CLINICAL_FIELDS:
        value = getattr(data, name)
        if name in sent and not (value is None and name in required) and getattr(patient, name) != value:
            if name == "mrn" and await _mrn_taken(db, patient.hospital_id, value, exclude=patient.id):
                raise MRN_TAKEN
            setattr(patient, name, value)
            changed.append(name)
    if "medical_history" in sent and data.medical_history is not None:
        history = data.medical_history.model_dump(exclude_none=True)
        if history != (patient.medical_history or {}):
            patient.medical_history = history
            changed.append("medical_history")

    if "date_of_birth" in changed:
        patient.age_band = age_band(ident.date_of_birth)
    if "consent_status" in changed:
        patient.consent_at = _now() if patient.consent_status else None
    if "full_name" in changed and patient.user_id is not None:
        account = await db.get(User, patient.user_id)
        if account is not None:
            account.full_name = ident.full_name

    if changed:
        # Field names only: the audit trail must not become a second copy of the patient's identity.
        await write_audit(db, "patient.update", user=actor, entity_type="patient", entity_id=patient.id,
                          details={"fields": changed}, request=request)
        await db.commit()
    return await patient_out(db, patient)


async def create_invite(db: AsyncSession, scope: Scope, patient_id: uuid.UUID, actor: User,
                        request: Request) -> InviteOut:
    patient = await patient_in_scope(db, scope, patient_id)
    if patient.user_id is not None:
        raise AppError(409, "ALREADY_ACTIVATED", "This patient already has a patient-portal account")
    now = _now()
    # Only the newest code works: issuing a new one retires any earlier unused code.
    await db.execute(update(PatientInvite).where(
        PatientInvite.patient_id == patient.id, PatientInvite.used_at.is_(None), PatientInvite.expires_at > now,
    ).values(expires_at=now))
    code = generate_invite_code()
    expires = now + timedelta(days=settings.invite_valid_days)
    db.add(PatientInvite(patient_id=patient.id, code_hash=sha256_hex(normalize_invite_code(code)),
                         expires_at=expires, created_by=actor.id))
    await write_audit(db, "patient.invite", user=actor, entity_type="patient", entity_id=patient.id,
                      details={"expires_at": expires.isoformat()}, request=request)
    await db.commit()
    return InviteOut(invite_code=code, expires_at=expires)
