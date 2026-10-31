"""Dashboards and the subgroup fairness report (S1). Registered before the reports router so that
/reports/subgroup-performance is not taken for a report id."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.core.errors import AppError
from app.models import User
from app.schemas.monitoring import HospitalActivity, PredictionPoint, SubgroupReport
from app.services import monitoring

router = APIRouter(tags=["monitoring"])
AIResults = Depends(require_roles("hospital_admin", "doctor"))


@router.get("/reports/subgroup-performance", response_model=SubgroupReport)
async def subgroup_performance(date_from: date | None = Query(None, alias="from"),
                               date_to: date | None = Query(None, alias="to"),
                               hospital_id: uuid.UUID | None = Query(None, description="Super admin only"),
                               _: User = Depends(require_roles("super_admin", "hospital_admin", "doctor")),
                               scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise AppError(422, "VALIDATION_ERROR", "The start date is after the end date")
    if scope.role != "super_admin":
        hospital_id = scope.hospital_id  # hospital staff always get their own hospital
    return await monitoring.subgroup_performance(db, hospital_id=hospital_id, date_from=date_from, date_to=date_to)


@router.get("/hospital/activity", response_model=HospitalActivity)
async def hospital_activity(months: int = Query(12, ge=1, le=24), _: User = AIResults,
                            scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await monitoring.hospital_activity(db, scope.hospital_id, months)


@router.get("/lesions/{lesion_id}/predictions", response_model=list[PredictionPoint])
async def lesion_predictions(lesion_id: uuid.UUID, _: User = AIResults, scope: Scope = Depends(get_scope),
                             db: AsyncSession = Depends(get_db)):
    return await monitoring.lesion_history(db, scope, lesion_id)
