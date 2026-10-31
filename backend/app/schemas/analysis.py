"""API schemas for analysis jobs, predictions and explanations (P3)."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.review import ReviewOut


class AnalyzeIn(BaseModel):
    visit_id: uuid.UUID | None = None  # default: the latest non-excluded visit with scans


class JobQueued(BaseModel):
    job_id: uuid.UUID
    status: str


class ModelInfo(BaseModel):
    name: str
    version: str
    is_mock: bool


class JobOut(BaseModel):
    """What technicians see: progress only, never the result."""
    id: uuid.UUID
    lesion_id: uuid.UUID
    trigger_visit_id: uuid.UUID
    status: str
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    model: ModelInfo | None


class JobDetailOut(JobOut):
    """For hospital admins and doctors."""
    prediction_id: uuid.UUID | None
    error: str | None


class JobListItem(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    finished_at: datetime | None
    patient_id: uuid.UUID
    patient_name: str
    mrn: str
    lesion_id: uuid.UUID
    lesion_label: str
    visit_date: date
    requested_by_name: str | None


class VisitFeatures(BaseModel):
    visit_id: uuid.UUID
    visit_date: date
    features: dict[str, float]
    melanoma_probability: float | None = None


class PredictionOut(BaseModel):
    id: uuid.UUID
    lesion_id: uuid.UUID
    visit_id: uuid.UUID
    visit_date: date
    job_id: uuid.UUID | None
    model: ModelInfo
    is_baseline: bool
    risk_score: float | None
    risk_category: str | None
    change_score: float | None
    uncertainty_score: float | None
    referral_flag: bool
    reason_codes: list[str]
    modality_mask: dict
    treatment_response: str | None
    inference_ms: int | None
    created_at: datetime
    visit_features: list[VisitFeatures]
    model_error: str | None
    reviewed: bool
    latest_review: ReviewOut | None = None


class ExplanationOut(BaseModel):
    prediction_id: uuid.UUID
    attention_weights: dict[str, float]
    difference_map_file_id: uuid.UUID | None
    saliency_file_id: uuid.UUID | None
    change_summary: list[str]
    registration_warning: bool
    saliency_passed_check: bool


class JobBrief(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    finished_at: datetime | None
