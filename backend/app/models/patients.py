import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CHAR, Date, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SexType, created_at_col, uuid_pk


class Patient(Base):
    """Clinical patient record. Holds no direct identifiers; those live in PatientIdentity."""
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = uuid_pk()
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True)
    mrn: Mapped[str] = mapped_column(String(50))
    pseudonym_id: Mapped[str] = mapped_column(String(20), unique=True)
    sex: Mapped[str] = mapped_column(SexType, default="unknown")
    age_band: Mapped[str | None] = mapped_column(String(10))
    fitzpatrick_type: Mapped[int | None] = mapped_column(SmallInteger)
    medical_history: Mapped[dict] = mapped_column(JSONB, default=dict)
    consent_status: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()

    identity: Mapped["PatientIdentity"] = relationship(back_populates="patient", uselist=False, lazy="joined")


class PatientIdentity(Base):
    """Personal identifiers (restricted). Never sent to the ml-service."""
    __tablename__ = "patient_identity"

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"),
                                                  primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(CITEXT)
    address: Mapped[str | None] = mapped_column(Text)

    patient: Mapped[Patient] = relationship(back_populates="identity")


class PatientInvite(Base):
    __tablename__ = "patient_invites"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(CHAR(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
