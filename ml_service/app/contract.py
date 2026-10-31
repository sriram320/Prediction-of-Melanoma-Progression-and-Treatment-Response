"""The ml-service contract. Keep this file identical to backend/app/schemas/inference.py (a backend test checks).

The backend sends only de-identified data. Every result passes through the backend safety wrapper, so an adapter
may return partial output; anything inconsistent is turned into a referral, never into a benign category.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

Modality = Literal["dermoscopic", "clinical_photo", "3d_tbp"]
RiskCategory = Literal["routine_monitoring", "shortened_interval", "specialist_referral"]
ReasonCode = Literal["low_image_quality", "registration_uncertain", "model_disagreement", "out_of_distribution",
                     "model_error", "segmentation_low_confidence", "ambiguous_prediction"]
TreatmentResponse = Literal["favourable", "persistent", "progression", "pending"]


class ImageInput(BaseModel):
    image_id: str
    modality: Modality
    sha256: str  # plaintext hash; lets the service cache embeddings per (image, model version)


class VisitInput(BaseModel):
    visit_id: str
    visit_date: date
    days_since_baseline: int
    device_model: Optional[str] = None
    illumination: Optional[str] = None
    polarised: Optional[bool] = None
    images: list[ImageInput]


class ClinicalInput(BaseModel):
    age_band: Optional[str] = None
    sex: Optional[str] = None
    anatomical_site: Optional[str] = None
    fitzpatrick_type: Optional[int] = None
    history: dict = {}


class TreatmentInput(BaseModel):
    treatment_type: str
    treatment_date: date


class LesionSequenceInput(BaseModel):
    lesion_ref: str  # pseudonymous reference, never a database id of a named patient
    visits: list[VisitInput]  # ascending by visit_date
    clinical: ClinicalInput
    treatments: list[TreatmentInput] = []


class ImageResult(BaseModel):
    image_id: str
    mask_png_b64: Optional[str] = None
    mask_confidence: Optional[float] = None
    quality_score: Optional[float] = None
    quality_flags: list[str] = []
    registration_transform: Optional[list[list[float]]] = None  # 3x3, maps this image onto the baseline
    registration_quality: Optional[float] = None


class VisitResult(BaseModel):
    """Optional per-visit outputs (Week 8): measured features and, if the model has one, a single-image score."""
    visit_id: str
    features: dict[str, float] = {}
    melanoma_probability: Optional[float] = Field(None, ge=0, le=1)


class PredictionOutput(BaseModel):
    model_name: str
    model_version: str
    is_mock: bool
    risk_score: Optional[float] = Field(None, ge=0, le=1)
    risk_category: Optional[RiskCategory] = None
    change_score: Optional[float] = Field(None, ge=0, le=1)
    uncertainty_score: Optional[float] = Field(None, ge=0, le=1)
    referral_flag: bool = False
    reason_codes: list[ReasonCode] = []
    attention_weights: dict[str, float] = {}  # visit_id -> weight (sum ~1)
    difference_map_png_b64: Optional[str] = None
    saliency_png_b64: Optional[str] = None
    saliency_passed_check: bool = True
    registration_warning: bool = False
    change_summary: list[str] = []  # template sentences only, never free text
    modality_mask: dict[str, bool] = {}  # {"dermoscopic": true, "clinical_photo": false, "3d_tbp": false, "metadata": true}
    treatment_response: Optional[TreatmentResponse] = None
    images: list[ImageResult] = []
    visits: list[VisitResult] = []
