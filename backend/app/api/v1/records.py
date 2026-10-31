"""Lesion timeline, visits and scan uploads."""
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.records import Modality, StaffTimelineOut, UploadResult, VisitCreate, VisitExclude, VisitOut
from app.services import records as records_svc

router = APIRouter(tags=["lesions & visits"])
Staff = Depends(require_roles("hospital_admin", "doctor", "technician"))


@router.get("/lesions/{lesion_id}/timeline", response_model=None,
            responses={200: {"model": StaffTimelineOut,
                             "description": "`latest_prediction` is present only for hospital admins and doctors"}})
async def timeline(lesion_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
                   db: AsyncSession = Depends(get_db)):
    return await records_svc.timeline(db, scope, lesion_id)


@router.post("/lesions/{lesion_id}/visits", response_model=VisitOut, status_code=status.HTTP_201_CREATED)
async def create_visit(lesion_id: uuid.UUID, body: VisitCreate, request: Request, actor: User = Staff,
                       scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await records_svc.create_visit(db, scope, lesion_id, body, actor, request)


@router.patch("/visits/{visit_id}", response_model=VisitOut)
async def exclude_visit(visit_id: uuid.UUID, body: VisitExclude, request: Request,
                        actor: User = Depends(require_roles("doctor")), scope: Scope = Depends(get_scope),
                        db: AsyncSession = Depends(get_db)):
    return await records_svc.set_visit_excluded(db, scope, visit_id, body, actor, request)


@router.post("/visits/{visit_id}/images", response_model=list[UploadResult])
async def upload_images(visit_id: uuid.UUID, request: Request, files: list[UploadFile] = File(...),
                        modality: Modality = Form("dermoscopic"), actor: User = Staff,
                        scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await records_svc.upload_images(db, scope, visit_id, files, modality, actor, request)
