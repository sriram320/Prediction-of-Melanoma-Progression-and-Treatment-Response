"""Declarative base and the PostgreSQL enum types created by migration 0001 (never re-created here)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def pg_enum(name: str, *values: str) -> ENUM:
    return ENUM(*values, name=name, create_type=False)


USER_ROLES = ("super_admin", "hospital_admin", "doctor", "technician", "patient")
STAFF_ROLES = ("hospital_admin", "doctor", "technician")
RISK_CATEGORIES = ("routine_monitoring", "shortened_interval", "specialist_referral")
DOCUMENT_CATEGORIES = ("lab_report", "prescription", "histopathology", "discharge_summary",
                       "referral_letter", "consent_form", "imaging_other", "other")

UserRole = pg_enum("user_role", *USER_ROLES)
ImageModality = pg_enum("image_modality", "dermoscopic", "clinical_photo", "3d_tbp")
RiskCategory = pg_enum("risk_category", *RISK_CATEGORIES)
JobStatus = pg_enum("job_status", "queued", "running", "succeeded", "failed", "cancelled")
ReportStatus = pg_enum("report_status", "draft", "pending_review", "signed", "released", "amended")
ResponseCategory = pg_enum("response_category", "favourable", "persistent", "progression", "pending")
ReviewDecision = pg_enum("review_decision", "confirmed", "overridden")
DocumentCategory = pg_enum("document_category", *DOCUMENT_CATEGORIES)
LesionStatus = pg_enum("lesion_status", "active", "excised", "closed")
SexType = pg_enum("sex_type", "male", "female", "other", "unknown")


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
