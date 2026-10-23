"""Hospital-admin console: staff accounts and hospital statistics (always scoped to the caller's hospital)."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.admin import HospitalStats, StaffCreate, StaffOut, StaffUpdate, StaffWithPassword
from app.schemas.common import Page
from app.services import hospitals as hospitals_svc
from app.services import staff as staff_svc

router = APIRouter(prefix="/hospital", tags=["hospital-admin"])
HospitalAdmin = Depends(require_roles("hospital_admin"))


@router.get("/staff", response_model=Page[StaffOut])
async def list_staff(role: Literal["hospital_admin", "doctor", "technician"] | None = None, q: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     _: User = HospitalAdmin, scope: Scope = Depends(get_scope),
                     db: AsyncSession = Depends(get_db)):
    return await staff_svc.list_staff(db, scope.hospital_id, role=role, q=q, page=page, page_size=page_size)


@router.post("/staff", response_model=StaffWithPassword, status_code=status.HTTP_201_CREATED)
async def create_staff(body: StaffCreate, request: Request, actor: User = HospitalAdmin,
                       scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await staff_svc.create_staff(db, scope.hospital_id, body, actor, request)


@router.patch("/staff/{user_id}", response_model=StaffWithPassword)
async def update_staff(user_id: uuid.UUID, body: StaffUpdate, request: Request, actor: User = HospitalAdmin,
                       scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await staff_svc.update_staff(db, scope.hospital_id, user_id, body, actor, request)


@router.get("/stats", response_model=HospitalStats)
async def stats(_: User = Depends(require_roles("hospital_admin", "doctor")), scope: Scope = Depends(get_scope),
                db: AsyncSession = Depends(get_db)):
    return await hospitals_svc.hospital_stats(db, scope.hospital_id)
