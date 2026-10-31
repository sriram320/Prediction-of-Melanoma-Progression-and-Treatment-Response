"""AI analysis: queue a job, follow it, and read predictions and explanations."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.analysis import AnalyzeIn, ExplanationOut, JobDetailOut, JobListItem, JobQueued, PredictionOut
from app.schemas.common import Page
from app.services import inference
from app.services import predictions as predictions_svc

router = APIRouter(tags=["analysis"])
Staff = Depends(require_roles("hospital_admin", "doctor", "technician"))
AIResults = Depends(require_roles(*predictions_svc.AI_RESULT_ROLES))


@router.post("/lesions/{lesion_id}/analyze", response_model=JobQueued, status_code=status.HTTP_202_ACCEPTED)
async def analyze(lesion_id: uuid.UUID, request: Request, body: AnalyzeIn | None = None,
                  actor: User = Depends(require_roles("doctor", "technician")), scope: Scope = Depends(get_scope),
                  db: AsyncSession = Depends(get_db)):
    return await inference.enqueue(db, scope, lesion_id, body.visit_id if body else None, actor, request)


@router.get("/jobs", response_model=Page[JobListItem])
async def list_jobs(lesion_id: uuid.UUID | None = None,
                    status_: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = Query(
                        None, alias="status"),
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Staff,
                    scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await predictions_svc.list_jobs(db, scope, lesion_id=lesion_id, status=status_, page=page,
                                           page_size=page_size)


@router.get("/jobs/{job_id}", response_model=None,
            responses={200: {"model": JobDetailOut,
                             "description": "`prediction_id` and `error` are omitted for technicians"}})
async def get_job(job_id: uuid.UUID, _: User = Staff, scope: Scope = Depends(get_scope),
                  db: AsyncSession = Depends(get_db)):
    return await predictions_svc.get_job(db, scope, job_id)


@router.get("/predictions/{prediction_id}", response_model=PredictionOut)
async def get_prediction(prediction_id: uuid.UUID, _: User = AIResults, scope: Scope = Depends(get_scope),
                         db: AsyncSession = Depends(get_db)):
    return await predictions_svc.get_prediction(db, scope, prediction_id)


@router.get("/predictions/{prediction_id}/explanation", response_model=ExplanationOut)
async def get_explanation(prediction_id: uuid.UUID, _: User = AIResults, scope: Scope = Depends(get_scope),
                          db: AsyncSession = Depends(get_db)):
    return await predictions_svc.get_explanation(db, scope, prediction_id)
