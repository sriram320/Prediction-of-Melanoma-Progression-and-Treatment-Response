"""Doctor review of AI results, the worklist, segmentation masks and treatment events (P4)."""
import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import blank_to_none

RiskCategoryT = Literal["routine_monitoring", "shortened_interval", "specialist_referral"]
TreatmentType = Literal["excision", "shave_biopsy", "punch_biopsy", "cryotherapy", "topical_therapy",
                        "immunotherapy", "targeted_therapy", "radiotherapy", "other"]


class ReviewIn(BaseModel):
    """The decision (confirmed / overridden) is derived from whether final_category matches the AI category."""
    final_category: RiskCategoryT
    reason: str | None = Field(default=None, max_length=2000)

    _blank = field_validator("reason", mode="before")(blank_to_none)


class ReviewOut(BaseModel):
    id: uuid.UUID
    prediction_id: uuid.UUID
    reviewer_name: str
    decision: str
    final_category: str
    reason: str | None
    created_at: datetime


class WorklistItem(BaseModel):
    prediction_id: uuid.UUID
    lesion_id: uuid.UUID
    lesion_label: str
    anatomical_site: str
    patient_id: uuid.UUID
    patient_name: str
    mrn: str
    visit_date: date
    is_baseline: bool
    referral_flag: bool
    reason_codes: list[str]
    risk_category: str | None
    risk_score: float | None
    is_mock: bool
    analysed_at: datetime
    final_category: str | None = None
    reviewed_at: datetime | None = None
    reviewer_name: str | None = None


Histopathology = Literal["melanoma", "not_melanoma"]
# Only tissue-sampling procedures can carry a histopathology result.
HISTOPATHOLOGY_TYPES = ("excision", "shave_biopsy", "punch_biopsy")


class TreatmentCreate(BaseModel):
    treatment_type: TreatmentType
    treatment_date: date
    notes: str | None = Field(default=None, max_length=2000)
    histopathology: Histopathology | None = None

    _blank = field_validator("notes", mode="before")(blank_to_none)

    @field_validator("treatment_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today() + timedelta(days=1):
            raise ValueError("Treatment date cannot be in the future")
        return v


class TreatmentUpdate(BaseModel):
    """Records (or corrects) the histopathology result when it comes back from the lab. null clears it."""
    histopathology: Histopathology | None


class TreatmentOut(BaseModel):
    id: uuid.UUID
    treatment_type: str
    treatment_date: date
    response_category: str
    notes: str | None
    histopathology: str | None = None
    histopathology_recorded_at: datetime | None = None
    created_at: datetime
