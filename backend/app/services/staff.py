"""Hospital staff accounts (hospital_admin, doctor, technician)."""
import uuid

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.core.security import generate_temp_password, hash_password
from app.models import User
from app.models.base import STAFF_ROLES
from app.schemas.admin import StaffCreate, StaffOut, StaffUpdate, StaffWithPassword
from app.schemas.common import Page
from app.services.audit import write_audit


async def list_staff(db: AsyncSession, hospital_id: uuid.UUID, *, role: str | None, q: str | None, page: int,
                     page_size: int) -> Page[StaffOut]:
    stmt = select(User).where(User.hospital_id == hospital_id, User.role.in_(STAFF_ROLES))
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(User.full_name).offset((page - 1) * page_size).limit(page_size))).all()
    return Page(items=[StaffOut.model_validate(u) for u in rows], total=total or 0, page=page, page_size=page_size)


async def create_staff(db: AsyncSession, hospital_id: uuid.UUID, data: StaffCreate, actor: User,
                       request: Request) -> StaffWithPassword:
    temp = generate_temp_password()
    user = User(hospital_id=hospital_id, role=data.role, full_name=data.full_name, email=data.email,
                phone=data.phone, registration_no=data.registration_no, password_hash=hash_password(temp),
                must_change_password=True)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "EMAIL_TAKEN", "A staff member with this email already exists in this hospital")
    await write_audit(db, "user.create", user=actor, hospital_id=hospital_id, entity_type="user",
                      entity_id=user.id, details={"role": data.role}, request=request)
    await db.commit()
    return StaffWithPassword(user=StaffOut.model_validate(user), temp_password=temp)


async def get_staff_member(db: AsyncSession, hospital_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.hospital_id != hospital_id or user.role not in STAFF_ROLES:
        raise not_found("Staff member")
    return user


async def update_staff(db: AsyncSession, hospital_id: uuid.UUID, user_id: uuid.UUID, data: StaffUpdate,
                       actor: User, request: Request) -> StaffWithPassword:
    user = await get_staff_member(db, hospital_id, user_id)
    if user.id == actor.id and data.is_active is False:
        raise AppError(400, "CANNOT_DEACTIVATE_SELF", "You cannot deactivate your own account")

    changed: list[str] = []
    for field in ("full_name", "phone", "registration_no", "is_active"):
        if field in data.model_fields_set:
            value = getattr(data, field)
            if field in ("full_name", "is_active") and value is None:
                continue
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed.append(field)
    temp = None
    if data.reset_password:
        temp = generate_temp_password()
        user.password_hash = hash_password(temp)
        user.must_change_password = True
        user.failed_login_count = 0
        user.locked_until = None
        changed.append("password_reset")
    if changed:
        await write_audit(db, "user.update", user=actor, hospital_id=hospital_id, entity_type="user",
                          entity_id=user.id, details={"fields": changed}, request=request)
        await db.commit()
    return StaffWithPassword(user=StaffOut.model_validate(user), temp_password=temp)
