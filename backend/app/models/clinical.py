import uuid
from datetime import date, datetime

from sqlalchemy import REAL, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (Base, DocumentCategory, ImageModality, LesionStatus, ResponseCategory,
                             created_at_col, uuid_pk)


class Lesion(Base):
    __tablename__ = "lesions"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    label: Mapped[str] = mapped_column(String(50))
    anatomical_site: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(LesionStatus, default="active")
    first_seen_visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="SET NULL", use_alter=True, name="fk_first_visit"))
    created_at: Mapped[datetime] = created_at_col()


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = uuid_pk()
    lesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lesions.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    visit_date: Mapped[date] = mapped_column(Date)
    device_model: Mapped[str | None] = mapped_column(String(100))
    illumination: Mapped[str | None] = mapped_column(String(30))
    polarised: Mapped[bool | None] = mapped_column(Boolean)
    quality_score: Mapped[float | None] = mapped_column(REAL)
    quality_flags: Mapped[list] = mapped_column(JSONB, default=list)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = uuid_pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("visits.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    modality: Mapped[str] = mapped_column(ImageModality)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stored_files.id"))
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(  # original DICOM; file_id holds the PNG
        UUID(as_uuid=True), ForeignKey("stored_files.id"))
    mask_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stored_files.id"))
    mask_confidence: Mapped[float | None] = mapped_column(REAL)
    mask_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    registration_transform: Mapped[list | None] = mapped_column(JSONB)
    registration_quality: Mapped[float | None] = mapped_column(REAL)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(REAL)
    quality_flags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = created_at_col()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    lesion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lesions.id"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stored_files.id"))
    category: Mapped[str] = mapped_column(DocumentCategory)
    title: Mapped[str] = mapped_column(String(200))
    document_date: Mapped[date | None] = mapped_column(Date)
    visible_to_patient: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class TreatmentEvent(Base):
    __tablename__ = "treatment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    lesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lesions.id", ondelete="CASCADE"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    treatment_type: Mapped[str] = mapped_column(String(50))
    treatment_date: Mapped[date] = mapped_column(Date)
    response_category: Mapped[str] = mapped_column(ResponseCategory, default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
