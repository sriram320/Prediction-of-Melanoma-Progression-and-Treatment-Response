"""Append-only audit logging (FR-15, NFR-10). The DB trigger fills prev_hash/row_hash.

Action names are fixed (api_contract.md §4); unknown actions are rejected so typos cannot slip in.
"""
import uuid

from fastapi import Request
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

ACTIONS = {
    "auth.login", "auth.login_failed", "auth.logout", "user.create", "user.update", "patient.create",
    "patient.update", "patient.invite", "patient.activate", "file.upload", "file.read", "visit.create",
    "visit.exclude", "mask.update", "job.create", "prediction.create", "prediction.review", "report.create",
    "report.sign", "report.release", "report.amend", "report.download", "document.visibility", "model.activate",
    # additions for P1 (documented in api_contract.md)
    "hospital.create", "hospital.update",
}


async def write_audit(
    db: AsyncSession,
    action: str,
    *,
    user: User | None = None,
    hospital_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    """Adds an audit row to the current transaction; the caller commits."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    await db.execute(
        insert(AuditLog).values(
            action=action,
            user_id=user.id if user else None,
            role=user.role if user else None,
            hospital_id=hospital_id if hospital_id is not None else (user.hospital_id if user else None),
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:500] if request else None,
        )
    )
