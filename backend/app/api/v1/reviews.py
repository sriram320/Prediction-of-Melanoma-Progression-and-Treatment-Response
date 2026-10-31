"""Doctor review of AI results, the worklist, lesion outlines (masks) and treatment events."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.common import Page
from app.schemas.records import ImageOut
from app.schemas.review import ReviewIn, ReviewOut, TreatmentCreate, TreatmentOut, TreatmentUpdate, WorklistItem
from app.services import reviews as reviews_svc

router = APIRouter(tags=["review"])
Doctor = Depends(require_roles("doctor"))
AIResults = Depends(require_roles("hospital_admin", "doctor"))
Staff = Depends(require_roles("hospital_admin", "doctor", "technician"))


@router.post("/predictions/{prediction_id}/review", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def review(prediction_id: uuid.UUID, body: ReviewIn, request: Request, actor: User = Doctor,
                 scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reviews_svc.review_prediction(db, scope, prediction_id, body, actor, request)


@router.get("/predictions/{prediction_id}/reviews", response_model=list[ReviewOut])
async def reviews(prediction_id: uuid.UUID, _: User = AIResults, scope: Scope = Depends(get_scope),
                  db: AsyncSession = Depends(get_db)):
    return await reviews_svc.list_reviews(db, scope, prediction_id)


@router.get("/worklist", response_model=Page[WorklistItem])
async def worklist(state: Literal["pending", "reviewed"] = "pending", page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), _: User = AIResults,
                   scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reviews_svc.worklist(db, scope, state=state, page=page, page_size=page_size)


@router.put("/images/{image_id}/mask", response_model=ImageOut)
async def set_mask(image_id: uuid.UUID, request: Request, file: UploadFile | None = File(None),
                   confirm: bool = Form(False), actor: User = Doctor, scope: Scope = Depends(get_scope),
                   db: AsyncSession = Depends(get_db)):
    return await reviews_svc.set_mask(db, scope, image_id, file, confirm, actor, request)


@router.get("/lesions/{lesion_id}/treatment-events", response_model=list[TreatmentOut])
async def treatments(lesion_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
                     db: AsyncSession = Depends(get_db)):
    return await reviews_svc.list_treatments(db, scope, lesion_id)


@router.post("/lesions/{lesion_id}/treatment-events", response_model=TreatmentOut,
             status_code=status.HTTP_201_CREATED)
async def create_treatment(lesion_id: uuid.UUID, body: TreatmentCreate, request: Request, actor: User = Doctor,
                           scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reviews_svc.create_treatment(db, scope, lesion_id, body, actor, request)


@router.patch("/treatment-events/{event_id}", response_model=TreatmentOut)
async def update_treatment(event_id: uuid.UUID, body: TreatmentUpdate, request: Request, actor: User = Doctor,
                           scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reviews_svc.update_treatment(db, scope, event_id, body, actor, request)
