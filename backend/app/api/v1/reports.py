"""Reports: draft, sign (renders PDFs), release, amend, download."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.common import Page
from app.schemas.reports import ReportCreate, ReportOut, ReportUpdate
from app.services import reports as reports_svc
from app.services.files import FILE_HEADERS, disposition

router = APIRouter(prefix="/reports", tags=["reports"])
Doctor = Depends(require_roles("doctor"))
Staff = Depends(require_roles("hospital_admin", "doctor", "technician"))


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create(body: ReportCreate, request: Request, actor: User = Doctor, scope: Scope = Depends(get_scope),
                 db: AsyncSession = Depends(get_db)):
    return await reports_svc.create_report(db, scope, body, actor, request)


@router.get("", response_model=Page[ReportOut])
async def list_reports(patient_id: uuid.UUID | None = None, lesion_id: uuid.UUID | None = None,
                       status_: Literal["draft", "pending_review", "signed", "released", "amended"] | None = Query(
                           None, alias="status"),
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Staff,
                       scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reports_svc.list_reports(db, scope, patient_id=patient_id, lesion_id=lesion_id, status=status_,
                                          page=page, page_size=page_size)


@router.get("/{report_id}", response_model=ReportOut)
async def get(report_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
              db: AsyncSession = Depends(get_db)):
    return await reports_svc.get_report(db, scope, report_id)


@router.patch("/{report_id}", response_model=ReportOut)
async def update(report_id: uuid.UUID, body: ReportUpdate, request: Request, actor: User = Doctor,
                 scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reports_svc.update_report(db, scope, report_id, body, actor, request)


@router.post("/{report_id}/sign", response_model=ReportOut)
async def sign(report_id: uuid.UUID, request: Request, actor: User = Doctor, scope: Scope = Depends(get_scope),
               db: AsyncSession = Depends(get_db)):
    return await reports_svc.sign_report(db, scope, report_id, actor, request)


@router.post("/{report_id}/release", response_model=ReportOut)
async def release(report_id: uuid.UUID, request: Request,
                  actor: User = Depends(require_roles("doctor", "hospital_admin")),
                  scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await reports_svc.release_report(db, scope, report_id, actor, request)


@router.post("/{report_id}/amend", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def amend(report_id: uuid.UUID, request: Request, actor: User = Doctor, scope: Scope = Depends(get_scope),
                db: AsyncSession = Depends(get_db)):
    return await reports_svc.amend_report(db, scope, report_id, actor, request)


@router.get("/{report_id}/pdf", response_class=Response)
async def pdf(report_id: uuid.UUID, request: Request, variant: Literal["patient", "clinician"] = "patient",
              download: bool = False,
              actor: User = Depends(require_roles("hospital_admin", "doctor", "technician", "patient")),
              scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    data, name = await reports_svc.report_pdf(db, scope, report_id, variant, actor, request)
    headers = {**FILE_HEADERS, "Content-Disposition": disposition("attachment" if download else "inline", name)}
    return Response(content=data, media_type="application/pdf", headers=headers)
