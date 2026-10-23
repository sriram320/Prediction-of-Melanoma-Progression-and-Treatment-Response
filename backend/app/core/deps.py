"""Request dependencies: current user, role checks and hospital/patient scoping.

Every route declares `Depends(require_roles(...))`; clinical routes also use `Depends(get_scope)`.
"""
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models import Patient, User

_bearer = HTTPBearer(auto_error=False)


async def _load_user(creds: HTTPAuthorizationCredentials | None, db: AsyncSession) -> tuple[User, dict]:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHENTICATED", "Not authenticated")
    try:
        claims = decode_access_token(creds.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise AppError(401, "INVALID_TOKEN", "Session expired or invalid")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "INVALID_TOKEN", "Session expired or invalid")
    if user.hospital is not None and not user.hospital.is_active:
        raise AppError(403, "HOSPITAL_INACTIVE", "This hospital account is inactive")
    return user, claims


async def get_current_user_allow_password_change(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: AsyncSession = Depends(get_db)
) -> User:
    """For /auth/me, /auth/change-password: usable while a password change is still pending."""
    user, _ = await _load_user(creds, db)
    return user


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: AsyncSession = Depends(get_db)
) -> User:
    user, _ = await _load_user(creds, db)
    if user.must_change_password:
        raise AppError(403, "PASSWORD_CHANGE_REQUIRED", "You must change your password before continuing")
    return user


def require_roles(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "FORBIDDEN", "You do not have permission for this action")
        return user

    return _check


@dataclass(frozen=True)
class Scope:
    user_id: uuid.UUID
    role: str
    hospital_id: uuid.UUID | None
    patient_id: uuid.UUID | None  # set only for patients

    @property
    def is_patient(self) -> bool:
        return self.role == "patient"

    def filter(self, stmt: Select, model) -> Select:
        """Restrict a query to the caller's hospital, and to their own record for patients."""
        if self.role != "super_admin":
            stmt = stmt.where(model.hospital_id == self.hospital_id)
        if self.is_patient:
            pid_col = model.id if model is Patient else getattr(model, "patient_id", None)
            if pid_col is None:
                raise RuntimeError(f"{model.__name__} cannot be scoped to a patient")
            stmt = stmt.where(pid_col == self.patient_id)
        return stmt


async def get_scope(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Scope:
    patient_id = None
    if user.role == "patient":
        patient_id = await db.scalar(select(Patient.id).where(Patient.user_id == user.id))
        if patient_id is None:
            raise AppError(403, "FORBIDDEN", "No patient record is linked to this account")
    return Scope(user_id=user.id, role=user.role, hospital_id=user.hospital_id, patient_id=patient_id)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
