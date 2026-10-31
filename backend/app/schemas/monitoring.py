"""Dashboards, the fairness report (S1) and the audit log viewer (S3) (P5)."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.analysis import ModelInfo


class PredictionPoint(BaseModel):
    """One analysis in a lesion's history, for the risk trend chart (HA, DR)."""
    prediction_id: uuid.UUID
    visit_id: uuid.UUID
    visit_date: date
    created_at: datetime
    model: ModelInfo
    is_baseline: bool
    risk_score: float | None
    risk_category: str | None
    uncertainty_score: float | None
    referral_flag: bool
    reason_codes: list[str]
    review_decision: str | None
    final_category: str | None


class MonthActivity(BaseModel):
    month: str  # YYYY-MM in DISPLAY_TIMEZONE
    visits: int
    analyses: int
    reviews: int
    reports_released: int


class HospitalActivity(BaseModel):
    months: list[MonthActivity]
    # Each lesion's newest result: routine_monitoring / shortened_interval / specialist_referral / referral /
    # baseline, plus not_analysed (active lesions without any result).
    current_results: dict[str, int]
    awaiting_review: int
    # Last 90 days. Overrides count only results that had an AI category (a referral has none to override).
    scored_reviews_90d: int
    overrides_90d: int
    review_median_hours_90d: float | None  # analysis finished -> first doctor review


class Accuracy(BaseModel):
    """Against histopathology. Flagged = anything other than routine monitoring (shortened interval, specialist
    referral, or a referral without a category)."""
    tp: int = 0
    fn: int = 0
    tn: int = 0
    fp: int = 0
    sensitivity: float | None = None
    specificity: float | None = None


class SubgroupRow(BaseModel):
    value: str | None  # None = not recorded
    n: int  # lesions with a current (newest, non-baseline) result in the period
    small_sample: bool
    referral_n: int
    referral_rate: float | None
    scored_n: int
    mean_risk: float | None
    routine_n: int
    shortened_n: int
    specialist_n: int
    reviewed_scored_n: int  # scored results with a doctor review (referrals have no AI category to override)
    override_n: int
    override_rate: float | None
    outcome_n: int  # lesions with a histopathology result and an earlier AI result
    melanoma_n: int
    ai: Accuracy
    after_review: Accuracy


class SubgroupDimension(BaseModel):
    key: str
    rows: list[SubgroupRow]


class CalibrationBin(BaseModel):
    lower: float
    upper: float
    n: int
    mean_risk: float | None
    observed_rate: float | None


class SubgroupReport(BaseModel):
    generated_at: datetime
    date_from: date | None
    date_to: date | None
    hospital_id: uuid.UUID | None
    hospital_name: str | None
    models: list[ModelInfo]
    any_mock: bool
    min_group_size: int
    overall: SubgroupRow
    dimensions: list[SubgroupDimension]
    calibration: list[CalibrationBin]


class AuditEntry(BaseModel):
    id: int
    occurred_at: datetime
    hospital_id: uuid.UUID | None
    hospital_code: str | None
    user_id: uuid.UUID | None
    actor_name: str | None
    role: str | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    ip: str | None
    user_agent: str | None
    details: dict
    prev_hash: str | None
    row_hash: str | None


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    hash_mismatches: int
    missing_links: int
    forks: int
    first_problem_id: int | None
    head_id: int | None
    head_hash: str | None
    verified_at: datetime
