"""Reports: draft -> signed (PDFs rendered, locked) -> released (visible to the patient) -> amended (superseded)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.analysis import ModelInfo
from app.schemas.common import blank_to_none
from app.schemas.review import RiskCategoryT


class ReportCreate(BaseModel):
    lesion_id: uuid.UUID
    prediction_id: uuid.UUID | None = None  # default: the lesion's latest prediction, if any


class ReportUpdate(BaseModel):
    final_category: RiskCategoryT | None = None
    patient_summary: str | None = Field(default=None, max_length=4000)
    recommendation: str | None = Field(default=None, max_length=500)
    doctor_notes: str | None = Field(default=None, max_length=8000)

    _blank = field_validator("patient_summary", "recommendation", "doctor_notes", mode="before")(blank_to_none)


class ReportOut(BaseModel):
    id: uuid.UUID
    report_number: str
    version: int
    status: str
    patient_id: uuid.UUID
    patient_name: str
    mrn: str
    lesion_id: uuid.UUID | None
    lesion_label: str | None
    anatomical_site: str | None
    prediction_id: uuid.UUID | None
    final_category: str | None
    category_from_review: bool = Field(description="True when the category is fixed by the doctor's review")
    patient_summary: str | None
    recommendation: str | None
    doctor_notes: str | None
    model: ModelInfo | None
    created_by_name: str | None
    signed_by_name: str | None
    signed_at: datetime | None
    released_at: datetime | None
    created_at: datetime
    supersedes_id: uuid.UUID | None
    supersedes_number: str | None
    superseded_by_id: uuid.UUID | None
    has_pdf: bool


class MyReport(BaseModel):
    """Patient view: the doctor's words only. No risk score, no model details."""
    id: uuid.UUID
    report_number: str
    version: int
    lesion_label: str | None
    anatomical_site: str | None
    final_category: str
    patient_summary: str | None
    recommendation: str | None
    signed_by_name: str | None
    signed_at: datetime | None
    released_at: datetime | None
