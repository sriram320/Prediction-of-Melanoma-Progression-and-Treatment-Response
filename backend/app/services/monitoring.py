"""Risk trends, hospital activity and the subgroup fairness report (S1, FR-12, NFR-05).

All figures are aggregates; nothing here returns patient identity. Re-running an analysis keeps the older results,
so per-lesion figures use each lesion's newest result unless stated otherwise.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Scope
from app.models import (ClinicianReview, Hospital, Lesion, ModelVersion, Patient, Prediction, Report, TreatmentEvent,
                        Visit)
from app.schemas.analysis import ModelInfo
from app.schemas.monitoring import (Accuracy, CalibrationBin, HospitalActivity, MonthActivity, PredictionPoint,
                                    SubgroupDimension, SubgroupReport, SubgroupRow)
from app.schemas.records import AnatomicalSite
from app.services.records import lesion_in_scope

FLAGGED = {"shortened_interval", "specialist_referral"}
MIN_GROUP_SIZE = 10  # below this a subgroup is shown but marked as too small to compare
DIMENSIONS = ("fitzpatrick_type", "anatomical_site", "device_model", "illumination")
SITE_ORDER = list(AnatomicalSite.__args__)
CALIBRATION_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.display_timezone)


def _float(v) -> float | None:
    return float(v) if v is not None else None


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _last_review():
    """The newest review of each prediction."""
    return (select(ClinicianReview.prediction_id, ClinicianReview.decision, ClinicianReview.final_category)
            .distinct(ClinicianReview.prediction_id)
            .order_by(ClinicianReview.prediction_id, ClinicianReview.created_at.desc())
            .subquery())


# ---------------------------------------------------------------- risk trend
async def lesion_history(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID) -> list[PredictionPoint]:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    review = _last_review()
    rows = (await db.execute(
        select(Prediction, Visit.visit_date, ModelVersion.name, ModelVersion.version, ModelVersion.is_mock,
               review.c.decision, review.c.final_category)
        .join(Visit, Prediction.visit_id == Visit.id)
        .join(ModelVersion, Prediction.model_version_id == ModelVersion.id)
        .outerjoin(review, review.c.prediction_id == Prediction.id)
        .where(Prediction.lesion_id == lesion.id)
        .order_by(Prediction.created_at))).all()
    return [PredictionPoint(
        prediction_id=p.id, visit_id=p.visit_id, visit_date=visit_date, created_at=p.created_at,
        model=ModelInfo(name=name, version=version, is_mock=is_mock), is_baseline=p.is_baseline,
        risk_score=_float(p.risk_score), risk_category=p.risk_category, uncertainty_score=_float(p.uncertainty_score),
        referral_flag=p.referral_flag, reason_codes=list(p.reason_codes or []), review_decision=decision,
        final_category=final) for p, visit_date, name, version, is_mock, decision, final in rows]


# ---------------------------------------------------------------- hospital activity
def _month_keys(months: int, tz: ZoneInfo) -> list[str]:
    now = datetime.now(tz)
    keys = []
    for back in range(months - 1, -1, -1):
        y, m = now.year, now.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        keys.append(f"{y:04d}-{m:02d}")
    return keys


def _month_of(col, tz: ZoneInfo):
    return func.to_char(func.date_trunc("month", func.timezone(tz.key, col)), "YYYY-MM")


async def hospital_activity(db: AsyncSession, hospital_id: uuid.UUID, months: int) -> HospitalActivity:
    tz = _tz()
    keys = _month_keys(months, tz)
    start = datetime(int(keys[0][:4]), int(keys[0][5:]), 1, tzinfo=tz)

    async def per_month(stmt) -> dict[str, int]:
        return {k: int(n) for k, n in (await db.execute(stmt)).all()}

    visit_month = func.to_char(Visit.visit_date, "YYYY-MM")
    visits = await per_month(select(visit_month, func.count()).where(
        Visit.hospital_id == hospital_id, Visit.visit_date >= start.date()).group_by(visit_month))
    pred_month = _month_of(Prediction.created_at, tz)
    analyses = await per_month(select(pred_month, func.count()).where(
        Prediction.hospital_id == hospital_id, Prediction.created_at >= start).group_by(pred_month))
    review_month = _month_of(ClinicianReview.created_at, tz)
    reviews = await per_month(select(review_month, func.count()).select_from(ClinicianReview)
                              .join(Prediction, ClinicianReview.prediction_id == Prediction.id)
                              .where(Prediction.hospital_id == hospital_id, ClinicianReview.created_at >= start)
                              .group_by(review_month))
    release_month = _month_of(Report.released_at, tz)
    released = await per_month(select(release_month, func.count()).where(
        Report.hospital_id == hospital_id, Report.released_at >= start).group_by(release_month))

    # Each lesion's newest result.
    latest = (select(Prediction.id, Prediction.is_baseline, Prediction.referral_flag, Prediction.risk_category)
              .where(Prediction.hospital_id == hospital_id)
              .distinct(Prediction.lesion_id).order_by(Prediction.lesion_id, Prediction.created_at.desc())
              .subquery())
    reviewed = select(ClinicianReview.prediction_id).where(ClinicianReview.prediction_id == latest.c.id).exists()
    current = {k: 0 for k in ("routine_monitoring", "shortened_interval", "specialist_referral", "referral",
                              "baseline", "not_analysed")}
    awaiting = 0
    for _, is_baseline, referral, category, is_reviewed in (await db.execute(select(latest, reviewed))).all():
        key = "referral" if referral else "baseline" if is_baseline else category
        current[key] += 1
        if not is_reviewed and (referral or not is_baseline):
            awaiting += 1
    current["not_analysed"] = int(await db.scalar(
        select(func.count(Lesion.id)).where(
            Lesion.hospital_id == hospital_id, Lesion.status == "active",
            ~select(Prediction.id).where(Prediction.lesion_id == Lesion.id).exists())) or 0)

    since = datetime.now(timezone.utc) - timedelta(days=90)
    scored = (Prediction.is_baseline.is_(False)) & (Prediction.referral_flag.is_(False))
    scored_reviews, overrides = (await db.execute(
        select(func.count(), func.count().filter(ClinicianReview.decision == "overridden"))
        .select_from(ClinicianReview).join(Prediction, ClinicianReview.prediction_id == Prediction.id)
        .where(Prediction.hospital_id == hospital_id, ClinicianReview.created_at >= since, scored))).one()
    first_review = (select(ClinicianReview.prediction_id, func.min(ClinicianReview.created_at).label("at"))
                    .group_by(ClinicianReview.prediction_id).subquery())
    hours = func.extract("epoch", first_review.c.at - Prediction.created_at) / 3600.0
    median = await db.scalar(
        select(func.percentile_cont(0.5).within_group(hours))
        .select_from(Prediction).join(first_review, first_review.c.prediction_id == Prediction.id)
        .where(Prediction.hospital_id == hospital_id, first_review.c.at >= since))

    return HospitalActivity(
        months=[MonthActivity(month=k, visits=visits.get(k, 0), analyses=analyses.get(k, 0),
                              reviews=reviews.get(k, 0), reports_released=released.get(k, 0)) for k in keys],
        current_results=current, awaiting_review=awaiting, scored_reviews_90d=int(scored_reviews or 0),
        overrides_90d=int(overrides or 0),
        review_median_hours_90d=round(float(median), 2) if median is not None else None)


# ---------------------------------------------------------------- fairness report
@dataclass
class _Result:
    lesion_id: uuid.UUID
    visit_date: date
    referral: bool
    category: str | None
    score: float | None
    decision: str | None
    final_category: str | None
    attrs: dict

    @property
    def ai_flagged(self) -> bool:
        return self.referral or self.category in FLAGGED


def _accuracy(pairs: list[tuple[_Result, bool]], flagged) -> Accuracy:
    acc = Accuracy()
    for res, melanoma in pairs:
        f = flagged(res)
        if f is None:
            continue
        if melanoma:
            acc.tp, acc.fn = acc.tp + f, acc.fn + (not f)
        else:
            acc.fp, acc.tn = acc.fp + f, acc.tn + (not f)
    acc.sensitivity = _rate(acc.tp, acc.tp + acc.fn)
    acc.specificity = _rate(acc.tn, acc.tn + acc.fp)
    return acc


def _after_review_flagged(res: _Result) -> bool | None:
    return None if res.final_category is None else res.final_category in FLAGGED


def _row(value, current: list[_Result], pairs: list[tuple[_Result, bool]]) -> SubgroupRow:
    scored = [r for r in current if not r.referral and r.score is not None]
    reviewed = [r for r in scored if r.decision is not None]
    overrides = sum(1 for r in reviewed if r.decision == "overridden")
    referrals = sum(1 for r in current if r.referral)
    return SubgroupRow(
        value=value, n=len(current), small_sample=len(current) < MIN_GROUP_SIZE,
        referral_n=referrals, referral_rate=_rate(referrals, len(current)),
        scored_n=len(scored), mean_risk=round(sum(r.score for r in scored) / len(scored), 4) if scored else None,
        routine_n=sum(1 for r in scored if r.category == "routine_monitoring"),
        shortened_n=sum(1 for r in scored if r.category == "shortened_interval"),
        specialist_n=sum(1 for r in scored if r.category == "specialist_referral"),
        reviewed_scored_n=len(reviewed), override_n=overrides, override_rate=_rate(overrides, len(reviewed)),
        outcome_n=len(pairs), melanoma_n=sum(1 for _, m in pairs if m),
        ai=_accuracy(pairs, lambda r: r.ai_flagged), after_review=_accuracy(pairs, _after_review_flagged))


def _order(dimension: str, values: set, counts: dict) -> list:
    if dimension == "fitzpatrick_type":
        return sorted((v for v in values if v is not None)) + ([None] if None in values else [])
    if dimension == "anatomical_site":
        return sorted(values, key=lambda v: SITE_ORDER.index(v) if v in SITE_ORDER else len(SITE_ORDER))
    return sorted(values, key=lambda v: (v is None, -counts.get(v, 0), str(v)))


def _calibration(pairs: list[tuple[_Result, bool]]) -> list[CalibrationBin]:
    bins = []
    edges = CALIBRATION_EDGES
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        last = i == len(edges) - 2
        inside = [(r, m) for r, m in pairs if not r.referral and r.score is not None
                  and lo <= r.score and (r.score <= hi if last else r.score < hi)]
        bins.append(CalibrationBin(
            lower=lo, upper=hi, n=len(inside),
            mean_risk=round(sum(r.score for r, _ in inside) / len(inside), 4) if inside else None,
            observed_rate=_rate(sum(1 for _, m in inside if m), len(inside))))
    return bins


def _window(stmt, column, date_from: date | None, date_to: date | None):
    tz = _tz()
    if date_from:
        stmt = stmt.where(column >= datetime.combine(date_from, time.min, tz))
    if date_to:
        stmt = stmt.where(column < datetime.combine(date_to + timedelta(days=1), time.min, tz))
    return stmt


async def subgroup_performance(db: AsyncSession, *, hospital_id: uuid.UUID | None, date_from: date | None,
                               date_to: date | None) -> SubgroupReport:
    """Results analysed in the period, grouped by skin type, body site, device and illumination.

    Rates use each lesion's newest scored-or-referred result in the period. Sensitivity and specificity use, for each
    lesion with a histopathology result, the newest result from a visit on or before the biopsy/excision date.
    """
    review = _last_review()
    stmt = (select(Prediction.lesion_id, Prediction.created_at, Prediction.referral_flag, Prediction.risk_category,
                   Prediction.risk_score, Visit.visit_date, Visit.device_model, Visit.illumination,
                   Lesion.anatomical_site, Patient.fitzpatrick_type, ModelVersion.name, ModelVersion.version,
                   ModelVersion.is_mock, review.c.decision, review.c.final_category)
            .join(Visit, Prediction.visit_id == Visit.id)
            .join(Lesion, Prediction.lesion_id == Lesion.id)
            .join(Patient, Lesion.patient_id == Patient.id)
            .join(ModelVersion, Prediction.model_version_id == ModelVersion.id)
            .outerjoin(review, review.c.prediction_id == Prediction.id)
            .where(Prediction.is_baseline.is_(False)))
    if hospital_id is not None:
        stmt = stmt.where(Prediction.hospital_id == hospital_id)
    stmt = _window(stmt, Prediction.created_at, date_from, date_to)
    rows = (await db.execute(stmt.order_by(Prediction.lesion_id, Prediction.created_at.desc()))).all()

    by_lesion: dict[uuid.UUID, list[_Result]] = defaultdict(list)
    models: dict[tuple, ModelInfo] = {}
    for r in rows:
        by_lesion[r.lesion_id].append(_Result(
            lesion_id=r.lesion_id, visit_date=r.visit_date, referral=r.referral_flag, category=r.risk_category,
            score=_float(r.risk_score), decision=r.decision, final_category=r.final_category,
            attrs={"fitzpatrick_type": r.fitzpatrick_type, "anatomical_site": r.anatomical_site,
                   "device_model": r.device_model, "illumination": r.illumination}))
        models[(r.name, r.version)] = ModelInfo(name=r.name, version=r.version, is_mock=r.is_mock)

    # The newest histopathology result of each lesion.
    outcome_stmt = (select(TreatmentEvent.lesion_id, TreatmentEvent.treatment_date, TreatmentEvent.histopathology)
                    .where(TreatmentEvent.histopathology.is_not(None))
                    .distinct(TreatmentEvent.lesion_id)
                    .order_by(TreatmentEvent.lesion_id, TreatmentEvent.treatment_date.desc()))
    if hospital_id is not None:
        outcome_stmt = outcome_stmt.where(TreatmentEvent.hospital_id == hospital_id)

    current = [results[0] for results in by_lesion.values()]
    pairs: list[tuple[_Result, bool]] = []
    for lid, when, result in (await db.execute(outcome_stmt)).all():
        before = next((r for r in by_lesion.get(lid, []) if r.visit_date <= when), None)
        if before is not None:
            pairs.append((before, result == "melanoma"))

    dimensions = []
    for dim in DIMENSIONS:
        cur_groups: dict = defaultdict(list)
        pair_groups: dict = defaultdict(list)
        for r in current:
            cur_groups[r.attrs[dim]].append(r)
        for res, m in pairs:
            pair_groups[res.attrs[dim]].append((res, m))
        values = set(cur_groups) | set(pair_groups)
        counts = {v: len(cur_groups.get(v, [])) for v in values}
        dimensions.append(SubgroupDimension(key=dim, rows=[
            _row(None if v is None else str(v), cur_groups.get(v, []), pair_groups.get(v, []))
            for v in _order(dim, values, counts)]))

    hospital = await db.get(Hospital, hospital_id) if hospital_id else None
    return SubgroupReport(
        generated_at=datetime.now(timezone.utc), date_from=date_from, date_to=date_to, hospital_id=hospital_id,
        hospital_name=hospital.name if hospital else None,
        models=sorted(models.values(), key=lambda m: (m.name, m.version)),
        any_mock=any(m.is_mock for m in models.values()), min_group_size=MIN_GROUP_SIZE,
        overall=_row("all", current, pairs), dimensions=dimensions, calibration=_calibration(pairs))
