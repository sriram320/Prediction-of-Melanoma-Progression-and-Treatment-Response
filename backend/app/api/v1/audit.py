"""Audit log viewer (S3, FR-15). The log itself is append-only; nothing here changes it."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.core.errors import AppError
from app.models import User
from app.schemas.common import Page
from app.schemas.monitoring import AuditEntry, AuditVerifyOut
from app.services import audit_log
from app.services.audit import ACTIONS

router = APIRouter(prefix="/audit", tags=["audit"])
Auditors = Depends(require_roles("super_admin", "hospital_admin"))


@router.get("", response_model=Page[AuditEntry])
async def search(action: str | None = Query(None, description="An action, or a group such as `report`"),
                 user_id: uuid.UUID | None = None, entity_type: str | None = None,
                 entity_id: uuid.UUID | None = None,
                 hospital_id: uuid.UUID | None = Query(None, description="Super admin only"),
                 date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), _: User = Auditors,
                 scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise AppError(422, "VALIDATION_ERROR", "The start date is after the end date")
    return await audit_log.search(db, scope, action=action, user_id=user_id, entity_type=entity_type,
                                  entity_id=entity_id, hospital_id=hospital_id, date_from=date_from,
                                  date_to=date_to, page=page, page_size=page_size)


@router.get("/actions", response_model=list[str])
async def actions(_: User = Auditors):
    return sorted(ACTIONS)


@router.post("/verify", response_model=AuditVerifyOut)
async def verify(request: Request, actor: User = Depends(require_roles("super_admin")),
                 db: AsyncSession = Depends(get_db)):
    return await audit_log.verify_chain(db, actor, request)


@router.get("/{prediction_id}", response_model=list[AuditEntry])
async def prediction_trail(prediction_id: uuid.UUID,
                           _: User = Depends(require_roles("super_admin", "hospital_admin", "doctor")),
                           scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await audit_log.prediction_trail(db, scope, prediction_id)
