"""Schemas for patient records, lesions, visits, images and documents (P2)."""
import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.analysis import JobBrief, PredictionOut
from app.schemas.common import ORMModel, blank_to_none, normalize_phone

Sex = Literal["male", "female", "other", "unknown"]
Modality = Literal["dermoscopic", "clinical_photo", "3d_tbp"]
DocumentCategoryT = Literal["lab_report", "prescription", "histopathology", "discharge_summary",
                            "referral_letter", "consent_form", "imaging_other", "other"]
# ISIC "anatom_site_general" groups, so subgroup (fairness) reports line up with the training data.
AnatomicalSite = Literal["head_neck", "anterior_torso", "posterior_torso", "lateral_torso", "upper_extremity",
                         "lower_extremity", "palms_soles", "oral_genital", "unknown"]


def _not_future(d: date, what: str) -> date:
    if d > date.today() + timedelta(days=1):  # one day of slack for server/clinic time-zone differences
        raise ValueError(f"{what} cannot be in the future")
    return d


def _valid_dob(d: date) -> date:
    _not_future(d, "Date of birth")
    if d < date.today() - timedelta(days=365 * 130):
        raise ValueError("Date of birth is not plausible")
    return d


class MedicalHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prior_melanoma: bool | None = None
    family_history_melanoma: bool | None = None
    many_naevi: bool | None = Field(default=None, description="More than 50 moles")
    immunosuppressed: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    _blank = field_validator("notes", mode="before")(blank_to_none)


class PatientCreate(BaseModel):
    mrn: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=2, max_length=200)
    date_of_birth: date
    sex: Sex = "unknown"
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)
    fitzpatrick_type: int | None = Field(default=None, ge=1, le=6)
    medical_history: MedicalHistory = MedicalHistory()
    consent_status: bool = False

    _blank = field_validator("email", "address", mode="before")(blank_to_none)

    @field_validator("mrn", "full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: date) -> date:
        return _valid_dob(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class PatientUpdate(BaseModel):
    mrn: str | None = Field(default=None, min_length=1, max_length=50)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)
    fitzpatrick_type: int | None = Field(default=None, ge=1, le=6)
    medical_history: MedicalHistory | None = None
    consent_status: bool | None = None

    _blank = field_validator("email", "address", mode="before")(blank_to_none)

    @field_validator("mrn", "full_name")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v):
        return _valid_dob(v) if v is not None else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class PatientListItem(BaseModel):
    id: uuid.UUID
    mrn: str
    pseudonym_id: str
    full_name: str
    date_of_birth: date
    sex: str
    age_band: str | None
    fitzpatrick_type: int | None
    has_account: bool
    lesion_count: int
    last_visit_date: date | None
    created_at: datetime


class InviteStatus(BaseModel):
    expires_at: datetime
    created_at: datetime


class PatientOut(BaseModel):
    id: uuid.UUID
    mrn: str
    pseudonym_id: str
    full_name: str
    date_of_birth: date
    sex: str
    age_band: str | None
    fitzpatrick_type: int | None
    phone: str | None
    email: str | None
    address: str | None
    medical_history: dict
    consent_status: bool
    consent_at: datetime | None
    has_account: bool
    pending_invite: InviteStatus | None
    lesion_count: int
    document_count: int
    created_at: datetime


class InviteOut(BaseModel):
    invite_code: str = Field(description="Shown once. The patient enters it with their date of birth.")
    expires_at: datetime


class LesionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    anatomical_site: AnatomicalSite

    @field_validator("label")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LesionOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    label: str
    anatomical_site: str
    status: str
    created_at: datetime
    visit_count: int
    first_visit_date: date | None
    last_visit_date: date | None
    latest_image_file_id: uuid.UUID | None


class VisitCreate(BaseModel):
    visit_date: date
    device_model: str | None = Field(default=None, max_length=100)
    illumination: str | None = Field(default=None, max_length=30)
    polarised: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    _blank = field_validator("device_model", "illumination", "notes", mode="before")(blank_to_none)

    @field_validator("visit_date")
    @classmethod
    def _date(cls, v: date) -> date:
        return _not_future(v, "Visit date")


class VisitExclude(BaseModel):
    excluded: bool
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


def _round_score(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None  # stored as REAL (float32)


class ImageOut(ORMModel):
    id: uuid.UUID
    modality: str
    file_id: uuid.UUID
    width: int | None
    height: int | None
    quality_score: float | None
    quality_flags: list[str]
    created_at: datetime
    # Segmentation outline (an AI output): filled for hospital admins and doctors only
    mask_file_id: uuid.UUID | None = None
    mask_confidence: float | None = None
    mask_confirmed: bool = False

    _round = field_validator("quality_score", "mask_confidence")(_round_score)


class VisitOut(ORMModel):
    id: uuid.UUID
    visit_date: date
    device_model: str | None
    illumination: str | None
    polarised: bool | None
    quality_score: float | None
    quality_flags: list[str]
    excluded: bool
    notes: str | None
    created_at: datetime
    images: list[ImageOut] = []

    _round = field_validator("quality_score")(_round_score)


class PatientBrief(BaseModel):
    id: uuid.UUID
    mrn: str
    pseudonym_id: str
    full_name: str
    sex: str
    age_band: str | None
    fitzpatrick_type: int | None


class TimelineOut(BaseModel):
    lesion: LesionOut
    patient: PatientBrief
    visits: list[VisitOut]
    analysable_visit_count: int = Field(description="Non-excluded visits with at least one image")
    treatment_events: list[dict] = []
    latest_job: JobBrief | None = None


class StaffTimelineOut(TimelineOut):
    """Timeline for hospital admins and doctors. Technicians get TimelineOut, without the prediction key."""
    latest_prediction: PredictionOut | None = None


class UploadResult(BaseModel):
    filename: str
    image_id: uuid.UUID | None = None
    file_id: uuid.UUID | None = None
    duplicate: bool = False
    duplicate_visit_date: date | None = None
    quality_score: float | None = None
    quality_flags: list[str] = []
    error: str | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    lesion_id: uuid.UUID | None
    file_id: uuid.UUID
    category: str
    title: str
    document_date: date | None
    visible_to_patient: bool
    mime_type: str
    size_bytes: int
    original_filename: str | None
    uploaded_by_name: str | None
    created_at: datetime


class DocumentVisibility(BaseModel):
    visible_to_patient: bool


# ---------- Patient portal (/me) ----------
class MyImage(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    modality: str
    width: int | None
    height: int | None


class MyVisit(BaseModel):
    id: uuid.UUID
    visit_date: date
    images: list[MyImage]


class MyLesion(BaseModel):
    id: uuid.UUID
    label: str
    anatomical_site: str
    status: str
    visits: list[MyVisit]


class MyDocument(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    document_date: date | None
    file_id: uuid.UUID
    mime_type: str
    size_bytes: int
    created_at: datetime


class MyOverview(BaseModel):
    full_name: str
    hospital_name: str
    mrn: str
    lesion_count: int
    visit_count: int
    document_count: int
    last_visit_date: date | None
    latest_report: dict | None = None
    upcoming_followup: date | None = None
