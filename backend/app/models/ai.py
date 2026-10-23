import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (ARRAY, Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text,
                        func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (Base, JobStatus, ResponseCategory, ReviewDecision, RiskCategory, created_at_col,
                             uuid_pk)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(50))
    version: Mapped[str] = mapped_column(String(30))
    adapter: Mapped[str] = mapped_column(String(50))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    model_card: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InferenceJob(Base):
    __tablename__ = "inference_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    lesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lesions.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    trigger_visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("visits.id", ondelete="CASCADE"))
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    status: Mapped[str] = mapped_column(JobStatus, default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prediction(Base):
    """One model result. Invariant (DB CHECK + service layer): referral_flag => risk_category IS NULL."""
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = uuid_pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("visits.id", ondelete="CASCADE"))
    lesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lesions.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                     ForeignKey("inference_jobs.id", ondelete="SET NULL"))
    model_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    risk_category: Mapped[str | None] = mapped_column(RiskCategory)
    change_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    uncertainty_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    referral_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    modality_mask: Mapped[dict] = mapped_column(JSONB, default=dict)
    treatment_response: Mapped[str | None] = mapped_column(ResponseCategory)
    raw_output: Mapped[dict | None] = mapped_column(JSONB)
    inference_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_col()


class Explanation(Base):
    __tablename__ = "explanations"

    id: Mapped[uuid.UUID] = uuid_pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                     ForeignKey("predictions.id", ondelete="CASCADE"), unique=True)
    attention_weights: Mapped[dict] = mapped_column(JSONB, default=dict)
    difference_map_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                                      ForeignKey("stored_files.id"))
    saliency_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stored_files.id"))
    change_summary: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    registration_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    saliency_passed_check: Mapped[bool] = mapped_column(Boolean, default=True)


class ClinicianReview(Base):
    __tablename__ = "clinician_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                     ForeignKey("predictions.id", ondelete="CASCADE"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(ReviewDecision)
    final_category: Mapped[str] = mapped_column(RiskCategory)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
