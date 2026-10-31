"""Reading predictions, explanations and jobs. AI results are for hospital admins and doctors only."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Scope
from app.core.errors import not_found
from app.models import (ClinicianReview, Explanation, InferenceJob, Lesion, ModelVersion, Patient, PatientIdentity,
                        Prediction, User, Visit)
from app.schemas.analysis import (ExplanationOut, JobBrief, JobDetailOut, JobListItem, JobOut, ModelInfo,
                                  PredictionOut, VisitFeatures)
from app.schemas.common import Page
from app.schemas.review import ReviewOut

AI_RESULT_ROLES = ("hospital_admin", "doctor")
ACTIVE_JOB = ("queued", "running")


async def model_info(db: AsyncSession, model_version_id: uuid.UUID | None) -> ModelInfo | None:
    mv = await db.get(ModelVersion, model_version_id) if model_version_id else None
    return ModelInfo(name=mv.name, version=mv.version, is_mock=mv.is_mock) if mv else None


def _float(v) -> float | None:
    return float(v) if v is not None else None


async def reviews_for(db: AsyncSession, prediction_id: uuid.UUID) -> list[ReviewOut]:
    rows = (await db.execute(select(ClinicianReview, User.full_name).join(User, ClinicianReview.reviewer_id == User.id)
                             .where(ClinicianReview.prediction_id == prediction_id)
                             .order_by(ClinicianReview.created_at.desc()))).all()
    return [ReviewOut(id=r.id, prediction_id=r.prediction_id, reviewer_name=name, decision=r.decision,
                      final_category=r.final_category, reason=r.reason, created_at=r.created_at) for r, name in rows]


async def latest_review(db: AsyncSession, prediction_id: uuid.UUID) -> ReviewOut | None:
    reviews = await reviews_for(db, prediction_id)
    return reviews[0] if reviews else None


async def prediction_out(db: AsyncSession, pred: Prediction) -> PredictionOut:
    raw = pred.raw_output or {}
    visit_dates = dict((await db.execute(select(Visit.id, Visit.visit_date)
                                         .where(Visit.lesion_id == pred.lesion_id))).all())
    features = []
    for v in raw.get("visits", []):
        try:
            vid = uuid.UUID(v["visit_id"])
        except (KeyError, ValueError):
            continue
        if vid in visit_dates:
            features.append(VisitFeatures(visit_id=vid, visit_date=visit_dates[vid], features=v.get("features", {}),
                                          melanoma_probability=v.get("melanoma_probability")))
    features.sort(key=lambda f: f.visit_date)
    review = await latest_review(db, pred.id)
    return PredictionOut(
        id=pred.id, lesion_id=pred.lesion_id, visit_id=pred.visit_id, visit_date=visit_dates.get(pred.visit_id),
        job_id=pred.job_id, model=await model_info(db, pred.model_version_id), is_baseline=pred.is_baseline,
        risk_score=_float(pred.risk_score), risk_category=pred.risk_category, change_score=_float(pred.change_score),
        uncertainty_score=_float(pred.uncertainty_score), referral_flag=pred.referral_flag,
        reason_codes=list(pred.reason_codes or []), modality_mask=pred.modality_mask or {},
        treatment_response=pred.treatment_response, inference_ms=pred.inference_ms, created_at=pred.created_at,
        visit_features=features, model_error=raw.get("error"), reviewed=review is not None,
        latest_review=review)


async def latest_prediction(db: AsyncSession, lesion_id: uuid.UUID) -> PredictionOut | None:
    pred = await db.scalar(select(Prediction).where(Prediction.lesion_id == lesion_id)
                           .order_by(Prediction.created_at.desc()).limit(1))
    return await prediction_out(db, pred) if pred else None


async def latest_job(db: AsyncSession, lesion_id: uuid.UUID) -> JobBrief | None:
    job = await db.scalar(select(InferenceJob).where(InferenceJob.lesion_id == lesion_id)
                          .order_by(InferenceJob.created_at.desc()).limit(1))
    return JobBrief(id=job.id, status=job.status, created_at=job.created_at,
                    finished_at=job.finished_at) if job else None


async def _prediction_in_scope(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> Prediction:
    pred = await db.get(Prediction, prediction_id)
    if pred is None or pred.hospital_id != scope.hospital_id:
        raise not_found("Prediction")
    return pred


async def get_prediction(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> PredictionOut:
    return await prediction_out(db, await _prediction_in_scope(db, scope, prediction_id))


async def get_explanation(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> ExplanationOut:
    pred = await _prediction_in_scope(db, scope, prediction_id)
    exp = await db.scalar(select(Explanation).where(Explanation.prediction_id == pred.id))
    if exp is None:
        return ExplanationOut(prediction_id=pred.id, attention_weights={}, difference_map_file_id=None,
                              saliency_file_id=None, change_summary=[], registration_warning=False,
                              saliency_passed_check=True)
    return ExplanationOut(prediction_id=pred.id, attention_weights=exp.attention_weights or {},
                          difference_map_file_id=exp.difference_map_file_id, saliency_file_id=exp.saliency_file_id,
                          change_summary=list(exp.change_summary or []), registration_warning=exp.registration_warning,
                          saliency_passed_check=exp.saliency_passed_check)


async def get_job(db: AsyncSession, scope: Scope, job_id: uuid.UUID) -> JobOut:
    job = await db.get(InferenceJob, job_id)
    if job is None or job.hospital_id != scope.hospital_id:
        raise not_found("Job")
    fields = dict(id=job.id, lesion_id=job.lesion_id, trigger_visit_id=job.trigger_visit_id, status=job.status,
                  attempts=job.attempts, created_at=job.created_at, started_at=job.started_at,
                  finished_at=job.finished_at, model=await model_info(db, job.model_version_id))
    if scope.role in AI_RESULT_ROLES:
        return JobDetailOut(**fields, prediction_id=job.prediction_id, error=job.error)
    return JobOut(**fields)


async def list_jobs(db: AsyncSession, scope: Scope, *, lesion_id: uuid.UUID | None, status: str | None, page: int,
                    page_size: int) -> Page[JobListItem]:
    stmt = (select(InferenceJob.id, InferenceJob.status, InferenceJob.created_at, InferenceJob.finished_at,
                   Patient.id.label("patient_id"), PatientIdentity.full_name.label("patient_name"), Patient.mrn,
                   Lesion.id.label("lesion_id"), Lesion.label.label("lesion_label"), Visit.visit_date,
                   User.full_name.label("requested_by_name"))
            .join(Lesion, InferenceJob.lesion_id == Lesion.id)
            .join(Patient, Lesion.patient_id == Patient.id)
            .join(PatientIdentity, PatientIdentity.patient_id == Patient.id)
            .join(Visit, InferenceJob.trigger_visit_id == Visit.id)
            .outerjoin(User, InferenceJob.requested_by == User.id)
            .where(InferenceJob.hospital_id == scope.hospital_id))
    if lesion_id:
        stmt = stmt.where(InferenceJob.lesion_id == lesion_id)
    if status:
        stmt = stmt.where(InferenceJob.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(InferenceJob.created_at.desc()).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    return Page(items=[JobListItem(**r._mapping) for r in rows], total=total or 0, page=page, page_size=page_size)
