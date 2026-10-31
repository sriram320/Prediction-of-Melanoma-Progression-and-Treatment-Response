"""Patient records, their lesions and documents. Staff only; always scoped to the caller's hospital."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.common import Page
from app.schemas.records import (DocumentCategoryT, DocumentOut, InviteOut, LesionCreate, LesionOut, PatientCreate,
                                 PatientListItem, PatientOut, PatientUpdate)
from app.services import documents as documents_svc
from app.services import patients as patients_svc
from app.services import records as records_svc

router = APIRouter(prefix="/patients", tags=["patients"])
Staff = Depends(require_roles("hospital_admin", "doctor", "technician"))


@router.get("", response_model=Page[PatientListItem])
async def list_patients(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1),
                        page_size: int = Query(20, ge=1, le=100), _: User = Staff,
                        scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await patients_svc.list_patients(db, scope, q=q, page=page, page_size=page_size)


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(body: PatientCreate, request: Request, actor: User = Staff,
                         scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await patients_svc.create_patient(db, scope, body, actor, request)


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
                      db: AsyncSession = Depends(get_db)):
    return await patients_svc.get_patient(db, scope, patient_id)


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(patient_id: uuid.UUID, body: PatientUpdate, request: Request, actor: User = Staff,
                         scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await patients_svc.update_patient(db, scope, patient_id, body, actor, request)


@router.post("/{patient_id}/invite", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(patient_id: uuid.UUID, request: Request, actor: User = Staff,
                        scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await patients_svc.create_invite(db, scope, patient_id, actor, request)


@router.get("/{patient_id}/lesions", response_model=list[LesionOut])
async def list_lesions(patient_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
                       db: AsyncSession = Depends(get_db)):
    return await records_svc.list_lesions(db, scope, patient_id)


@router.post("/{patient_id}/lesions", response_model=LesionOut, status_code=status.HTTP_201_CREATED)
async def create_lesion(patient_id: uuid.UUID, body: LesionCreate, request: Request, actor: User = Staff,
                        scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await records_svc.create_lesion(db, scope, patient_id, body, actor, request)


@router.get("/{patient_id}/documents", response_model=list[DocumentOut])
async def list_documents(patient_id: uuid.UUID, category: DocumentCategoryT | None = None, _: User = Staff,
                         scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await documents_svc.list_documents(db, scope, patient_id, category)


@router.post("/{patient_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(patient_id: uuid.UUID, request: Request, file: UploadFile = File(...),
                          category: DocumentCategoryT = Form(...), title: str = Form(..., max_length=200),
                          document_date: date | None = Form(None), lesion_id: uuid.UUID | None = Form(None),
                          visible_to_patient: bool = Form(False), actor: User = Staff,
                          scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await documents_svc.upload_document(
        db, scope, patient_id, file, category=category, title=title, document_date=document_date,
        lesion_id=lesion_id, visible_to_patient=visible_to_patient, actor=actor, request=request)
