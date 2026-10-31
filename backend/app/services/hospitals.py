"""Hospitals (tenants), managed by the super admin, plus per-hospital statistics."""
import uuid

from fastapi import Request
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models import ClinicianReview, Hospital, Lesion, Patient, Prediction, Report, User, Visit
from app.models.base import STAFF_ROLES
from app.schemas.admin import (HospitalCreate, HospitalDetailOut, HospitalOut, HospitalStats, HospitalUpdate,
                               StaffOut)
from app.schemas.common import Page
from app.services.audit import write_audit


def _staff_count():
    return (select(func.count(User.id))
            .where(User.hospital_id == Hospital.id, User.role.in_(STAFF_ROLES))
            .correlate(Hospital).scalar_subquery())


def _patient_count():
    return select(func.count(Patient.id)).where(Patient.hospital_id == Hospital.id).correlate(Hospital) \
        .scalar_subquery()


def _to_out(h: Hospital, staff: int, patients: int) -> HospitalOut:
    out = HospitalOut.model_validate(h)
    out.staff_count, out.patient_count = staff, patients
    return out


async def list_hospitals(db: AsyncSession, *, q: str | None, page: int, page_size: int) -> Page[HospitalOut]:
    base = select(Hospital)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(Hospital.name.ilike(like) | Hospital.code.ilike(like))
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    stmt = base.add_columns(_staff_count(), _patient_count()).order_by(Hospital.name) \
        .offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).all()
    return Page(items=[_to_out(h, s, p) for h, s, p in rows], total=total or 0, page=page, page_size=page_size)


async def get_hospital(db: AsyncSession, hospital_id: uuid.UUID) -> HospitalDetailOut:
    row = (await db.execute(select(Hospital, _staff_count(), _patient_count())
                            .where(Hospital.id == hospital_id))).first()
    if row is None:
        raise not_found("Hospital")
    h, staff, patients = row
    admins = (await db.scalars(select(User).where(User.hospital_id == h.id, User.role == "hospital_admin")
                               .order_by(User.full_name))).all()
    out = HospitalDetailOut.model_validate(h)
    out.staff_count, out.patient_count = staff, patients
    out.admins = [StaffOut.model_validate(u) for u in admins]
    return out


async def create_hospital(db: AsyncSession, data: HospitalCreate, actor: User, request: Request) -> HospitalOut:
    h = Hospital(**data.model_dump())
    db.add(h)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "CODE_TAKEN", f"Hospital code {data.code} is already in use")
    await write_audit(db, "hospital.create", user=actor, hospital_id=h.id, entity_type="hospital",
                      entity_id=h.id, details={"code": h.code}, request=request)
    await db.commit()
    return _to_out(h, 0, 0)


async def update_hospital(db: AsyncSession, hospital_id: uuid.UUID, data: HospitalUpdate, actor: User,
                          request: Request) -> HospitalDetailOut:
    h = await db.get(Hospital, hospital_id)
    if h is None:
        raise not_found("Hospital")
    changed = []
    for field in data.model_fields_set:
        value = getattr(data, field)
        if field in ("name", "is_active") and value is None:
            continue
        if getattr(h, field) != value:
            setattr(h, field, value)
            changed.append(field)
    if changed:
        await write_audit(db, "hospital.update", user=actor, hospital_id=h.id, entity_type="hospital",
                          entity_id=h.id, details={"fields": sorted(changed)}, request=request)
        await db.commit()
    return await get_hospital(db, hospital_id)


async def hospital_stats(db: AsyncSession, hospital_id: uuid.UUID) -> HospitalStats:
    unreviewed = ~exists().where(ClinicianReview.prediction_id == Prediction.id)
    # Re-running an analysis keeps the older results; only each lesion's newest one is awaiting review.
    latest = (select(Prediction.id).where(Prediction.hospital_id == hospital_id)
              .distinct(Prediction.lesion_id).order_by(Prediction.lesion_id, Prediction.created_at.desc()))
    current = Prediction.id.in_(latest)

    async def count(stmt) -> int:
        return int(await db.scalar(stmt) or 0)

    return HospitalStats(
        patients=await count(select(func.count(Patient.id)).where(Patient.hospital_id == hospital_id)),
        lesions=await count(select(func.count(Lesion.id)).where(Lesion.hospital_id == hospital_id)),
        visits=await count(select(func.count(Visit.id)).where(Visit.hospital_id == hospital_id)),
        pending_reviews=await count(select(func.count(Prediction.id)).where(
            Prediction.hospital_id == hospital_id, Prediction.is_baseline.is_(False), current, unreviewed)),
        open_referrals=await count(select(func.count(Prediction.id)).where(
            Prediction.hospital_id == hospital_id, Prediction.referral_flag.is_(True), current, unreviewed)),
        reports_released=await count(select(func.count(Report.id)).where(
            Report.hospital_id == hospital_id, Report.status == "released")),
        staff=await count(select(func.count(User.id)).where(
            User.hospital_id == hospital_id, User.role.in_(STAFF_ROLES), User.is_active.is_(True))),
    )
