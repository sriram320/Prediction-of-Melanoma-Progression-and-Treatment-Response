"""Reading the audit log (S3): search, the trail of one AI result, and hash-chain verification.

Hospital admins see their own hospital's entries; the super admin sees every hospital but not clinical free text
(reasons are redacted) and not patients' names. Writing stays in app.services.audit.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import AuditLog, Hospital, InferenceJob, Prediction, Report, User
from app.schemas.common import Page
from app.schemas.monitoring import AuditEntry, AuditVerifyOut
from app.services.audit import ACTIONS, write_audit

REDACTED_FOR_PLATFORM = ("reason",)  # free text that may describe the patient


def _entry(log: AuditLog, actor_name: str | None, actor_role: str | None, hospital_code: str | None,
           platform_view: bool) -> AuditEntry:
    details = dict(log.details or {})
    name = actor_name
    if platform_view:
        details = {k: ("[redacted]" if k in REDACTED_FOR_PLATFORM and v else v) for k, v in details.items()}
        if actor_role == "patient":
            name = None
    return AuditEntry(id=log.id, occurred_at=log.occurred_at, hospital_id=log.hospital_id,
                      hospital_code=hospital_code, user_id=log.user_id, actor_name=name, role=log.role,
                      action=log.action, entity_type=log.entity_type, entity_id=log.entity_id, ip=log.ip,
                      user_agent=log.user_agent, details=details, prev_hash=log.prev_hash, row_hash=log.row_hash)


def _base():
    return (select(AuditLog, User.full_name, User.role, Hospital.code)
            .outerjoin(User, AuditLog.user_id == User.id)
            .outerjoin(Hospital, AuditLog.hospital_id == Hospital.id))


async def search(db: AsyncSession, scope: Scope, *, action: str | None, user_id: uuid.UUID | None,
                 entity_type: str | None, entity_id: uuid.UUID | None, hospital_id: uuid.UUID | None,
                 date_from: date | None, date_to: date | None, page: int, page_size: int) -> Page[AuditEntry]:
    platform = scope.role == "super_admin"
    stmt = _base()
    if not platform:
        stmt = stmt.where(AuditLog.hospital_id == scope.hospital_id)
    elif hospital_id is not None:
        stmt = stmt.where(AuditLog.hospital_id == hospital_id)
    if action:
        if action in ACTIONS:
            stmt = stmt.where(AuditLog.action == action)
        elif any(a.startswith(f"{action}.") for a in ACTIONS):  # a group, e.g. "report"
            stmt = stmt.where(AuditLog.action.like(f"{action}.%"))
        else:
            raise AppError(422, "VALIDATION_ERROR", f"Unknown action: {action}")
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    tz = ZoneInfo(settings.display_timezone)
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= datetime.combine(date_from, time.min, tz))
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min, tz))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    return Page(items=[_entry(log, name, role, code, platform) for log, name, role, code in rows],
                total=total or 0, page=page, page_size=page_size)


async def prediction_trail(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> list[AuditEntry]:
    """Everything that happened to one AI result: its job, the result, reviews, and reports based on it."""
    pred = await db.get(Prediction, prediction_id)
    platform = scope.role == "super_admin"
    if pred is None or (not platform and pred.hospital_id != scope.hospital_id):
        raise not_found("Prediction")
    ids = {pred.id}
    if pred.job_id:
        ids.add(pred.job_id)
    ids |= set((await db.scalars(select(Report.id).where(Report.prediction_id == pred.id))).all())
    job_ids = (await db.scalars(select(InferenceJob.id).where(InferenceJob.prediction_id == pred.id))).all()
    ids |= set(job_ids)
    rows = (await db.execute(_base().where(AuditLog.entity_id.in_(ids), AuditLog.hospital_id == pred.hospital_id)
                             .order_by(AuditLog.id))).all()
    return [_entry(log, name, role, code, platform) for log, name, role, code in rows]


# Recomputes each row's hash exactly as the trg_audit_chain trigger did. occurred_at::text depends on the session
# time zone, so a row also passes if it matches the UTC rendering (a log written by a container in UTC).
_VERIFY_SQL = text("""
WITH chain AS (
  SELECT id, prev_hash, row_hash,
         encode(digest(coalesce(prev_hash,'') || occurred_at::text || coalesce(user_id::text,'') || action ||
                       coalesce(entity_id::text,'') || details::text, 'sha256'), 'hex') AS h_session,
         encode(digest(coalesce(prev_hash,'') || ((occurred_at AT TIME ZONE 'UTC')::text || '+00') ||
                       coalesce(user_id::text,'') || action || coalesce(entity_id::text,'') || details::text,
                       'sha256'), 'hex') AS h_utc
  FROM audit_log
), bad_hash AS (
  SELECT id FROM chain WHERE row_hash IS NULL OR (row_hash <> h_session AND row_hash <> h_utc)
), missing AS (
  SELECT c.id FROM audit_log c
  WHERE c.prev_hash IS NOT NULL AND NOT EXISTS (SELECT 1 FROM audit_log p WHERE p.row_hash = c.prev_hash)
), forks AS (
  SELECT prev_hash, min(id) AS id FROM audit_log GROUP BY prev_hash HAVING count(*) > 1
)
SELECT (SELECT count(*) FROM audit_log) AS checked,
       (SELECT count(*) FROM bad_hash) AS hash_mismatches,
       (SELECT count(*) FROM missing) AS missing_links,
       (SELECT count(*) FROM forks) AS forks,
       (SELECT min(id) FROM (SELECT id FROM bad_hash UNION ALL SELECT id FROM missing
                             UNION ALL SELECT id FROM forks) p) AS first_problem_id
""")


async def verify_chain(db: AsyncSession, actor: User, request: Request) -> AuditVerifyOut:
    """Super admin only: the chain spans every hospital.

    Detects edited rows (hash mismatch), deleted rows (a successor points at a missing hash) and spliced rows (two
    rows claim the same predecessor). Deleting the newest rows cannot be detected from inside the database, so the
    head hash is returned for keeping elsewhere.
    """
    r = (await db.execute(_VERIFY_SQL)).one()
    head = (await db.execute(select(AuditLog.id, AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1))).first()
    out = AuditVerifyOut(
        ok=r.hash_mismatches == 0 and r.missing_links == 0 and r.forks == 0, checked=r.checked,
        hash_mismatches=r.hash_mismatches, missing_links=r.missing_links, forks=r.forks,
        first_problem_id=r.first_problem_id, head_id=head.id if head else None,
        head_hash=head.row_hash if head else None, verified_at=datetime.now(timezone.utc))
    await write_audit(db, "audit.verify", user=actor,
                      details={"ok": out.ok, "checked": out.checked, "head_id": out.head_id}, request=request)
    await db.commit()
    return out
