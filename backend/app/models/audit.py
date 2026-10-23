import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UserRole


class AuditLog(Base):
    """Append-only (DB triggers block UPDATE/DELETE); prev_hash/row_hash are set by the trg_audit_chain trigger.
    Insert through app.services.audit.write_audit only."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str | None] = mapped_column(UserRole)
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(CHAR(64))
    row_hash: Mapped[str | None] = mapped_column(CHAR(64))
