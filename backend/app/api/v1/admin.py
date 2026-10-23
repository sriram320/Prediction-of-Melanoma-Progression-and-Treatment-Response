"""Super-admin console: hospitals (tenants) and their admin accounts."""
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_roles
from app.models import User
from app.schemas.admin import (HospitalAdminCreate, HospitalCreate, HospitalDetailOut, HospitalOut,
                               HospitalUpdate, StaffCreate, StaffWithPassword)
from app.schemas.common import Page
from app.services import hospitals as hospitals_svc
from app.services import staff as staff_svc

router = APIRouter(prefix="/admin", tags=["super-admin"])
SuperAdmin = Depends(require_roles("super_admin"))


@router.get("/hospitals", response_model=Page[HospitalOut])
async def list_hospitals(q: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         _: User = SuperAdmin, db: AsyncSession = Depends(get_db)):
    return await hospitals_svc.list_hospitals(db, q=q, page=page, page_size=page_size)


@router.post("/hospitals", response_model=HospitalOut, status_code=status.HTTP_201_CREATED)
async def create_hospital(body: HospitalCreate, request: Request, actor: User = SuperAdmin,
                          db: AsyncSession = Depends(get_db)):
    return await hospitals_svc.create_hospital(db, body, actor, request)


@router.get("/hospitals/{hospital_id}", response_model=HospitalDetailOut)
async def get_hospital(hospital_id: uuid.UUID, _: User = SuperAdmin, db: AsyncSession = Depends(get_db)):
    return await hospitals_svc.get_hospital(db, hospital_id)


@router.patch("/hospitals/{hospital_id}", response_model=HospitalDetailOut)
async def update_hospital(hospital_id: uuid.UUID, body: HospitalUpdate, request: Request,
                          actor: User = SuperAdmin, db: AsyncSession = Depends(get_db)):
    return await hospitals_svc.update_hospital(db, hospital_id, body, actor, request)


@router.post("/hospitals/{hospital_id}/admins", response_model=StaffWithPassword,
             status_code=status.HTTP_201_CREATED)
async def create_hospital_admin(hospital_id: uuid.UUID, body: HospitalAdminCreate, request: Request,
                                actor: User = SuperAdmin, db: AsyncSession = Depends(get_db)):
    await hospitals_svc.get_hospital(db, hospital_id)  # 404 if missing
    data = StaffCreate(role="hospital_admin", full_name=body.full_name, email=body.email, phone=body.phone)
    return await staff_svc.create_staff(db, hospital_id, data, actor, request)
