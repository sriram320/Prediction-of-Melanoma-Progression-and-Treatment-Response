"""Analysis jobs and the safety wrapper (model_integration.md §6).

Invariants enforced here, whatever the model returns:
- fewer than two analysable visits  -> baseline only: no risk score, no category;
- any model error, timeout, unreachable service, invalid or inconsistent output -> referral with `model_error`;
- an unconfirmed segmentation below the confidence threshold -> referral with `segmentation_low_confidence`;
- referral -> no category (the database CHECK enforces this too).
The model only ever receives de-identified data (pseudonym, age band, sex, site, skin type, yes/no history).
"""
import asyncio
import base64
import binascii
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import settings
from app.core.deps import Scope
from app.core.errors import AppError
from app.models import (Explanation, Image, InferenceJob, Lesion, ModelVersion, Patient, Prediction, StoredFile,
                        TreatmentEvent, User, Visit)
from app.schemas.analysis import JobQueued
from app.schemas.inference import (ClinicalInput, ImageInput, LesionSequenceInput, PredictionOutput, TreatmentInput,
                                   VisitInput)
from app.services import files as files_svc
from app.services import imaging, ml_client
from app.services.audit import write_audit
from app.services.patients import age_band
from app.services.records import lesion_in_scope

log = logging.getLogger("inference")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _usable_visits(db: AsyncSession, lesion_id: uuid.UUID) -> list[tuple[Visit, list[Image]]]:
    """Non-excluded visits that have at least one image, oldest first."""
    visits = (await db.scalars(select(Visit).where(Visit.lesion_id == lesion_id, Visit.excluded.is_(False))
                               .order_by(Visit.visit_date, Visit.created_at))).all()
    if not visits:
        return []
    images: dict[uuid.UUID, list[Image]] = {}
    for img in (await db.scalars(select(Image).where(Image.visit_id.in_([v.id for v in visits]))
                                 .order_by(Image.created_at))).all():
        images.setdefault(img.visit_id, []).append(img)
    return [(v, images[v.id]) for v in visits if v.id in images]


# ------------------------------------------------------------------ queueing
async def enqueue(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID, visit_id: uuid.UUID | None, actor: User,
                  request: Request) -> JobQueued:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    patient = await db.get(Patient, lesion.patient_id)
    if not patient.consent_status:
        raise AppError(409, "CONSENT_REQUIRED", "Record the patient's consent before running an AI analysis")
    usable = await _usable_visits(db, lesion.id)
    if not usable:
        raise AppError(409, "NO_SCANS", "Upload at least one scan before running an analysis")
    if visit_id is None:
        trigger = usable[-1][0]
    else:
        trigger = next((v for v, _ in usable if v.id == visit_id), None)
        if trigger is None:
            raise AppError(422, "VISIT_NOT_ANALYSABLE", "Choose a visit of this lesion that has scans and is not excluded")
    model = await db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    if model is None:
        raise AppError(503, "NO_ACTIVE_MODEL", "No AI model is active. Ask the platform administrator.")

    job = InferenceJob(lesion_id=lesion.id, hospital_id=lesion.hospital_id, trigger_visit_id=trigger.id,
                       model_version_id=model.id, requested_by=actor.id)
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:  # ux_jobs_one_active: another analysis of this lesion is queued or running
        await db.rollback()
        raise AppError(409, "JOB_IN_PROGRESS", "An analysis of this lesion is already queued or running")
    await write_audit(db, "job.create", user=actor, entity_type="inference_job", entity_id=job.id,
                      details={"lesion_id": str(lesion.id), "trigger_visit_id": str(trigger.id),
                               "model": f"{model.name} {model.version}"}, request=request)
    await db.commit()
    return JobQueued(job_id=job.id, status=job.status)


# ------------------------------------------------------------------ safety wrapper
@dataclass
class SafeResult:
    is_baseline: bool
    risk_score: float | None
    risk_category: str | None
    change_score: float | None
    uncertainty_score: float | None
    referral_flag: bool
    reason_codes: list[str]
    error: str | None = None
    output: PredictionOutput | None = None
    low_confidence_images: list[str] = field(default_factory=list)


def _inconsistency(out: PredictionOutput, model: ModelVersion, baseline: bool) -> str | None:
    if (out.model_name, out.model_version) != (model.name, model.version):
        return (f"The ml-service runs {out.model_name} {out.model_version}, but the active model is "
                f"{model.name} {model.version}")
    if out.is_mock != model.is_mock:
        return "The ml-service and the model registry disagree about whether this is a mock model"
    if not baseline and not out.referral_flag and not out.reason_codes and (
            out.risk_score is None or out.risk_category is None):
        return "The model returned neither a category nor a referral"
    return None


def apply_safety_wrapper(output: PredictionOutput | None, error: str | None, *, model: ModelVersion,
                         visit_count: int, confirmed_image_ids: set[str]) -> SafeResult:
    baseline = visit_count < 2
    if output is not None and (problem := _inconsistency(output, model, baseline)):
        output, error = None, problem
    if output is None:
        return SafeResult(is_baseline=baseline, risk_score=None, risk_category=None, change_score=None,
                          uncertainty_score=None, referral_flag=True, reason_codes=["model_error"],
                          error=error or "No model output")

    reasons = list(dict.fromkeys(output.reason_codes))
    low_conf = [r.image_id for r in output.images
                if r.mask_confidence is not None and r.mask_confidence < settings.segmentation_confidence_threshold
                and r.image_id not in confirmed_image_ids]
    if low_conf and "segmentation_low_confidence" not in reasons:
        reasons.append("segmentation_low_confidence")
    referral = output.referral_flag or bool(reasons)  # any reason code means a dermatologist must look
    return SafeResult(
        is_baseline=baseline, risk_score=None if baseline else output.risk_score,
        risk_category=None if (baseline or referral) else output.risk_category,
        change_score=None if baseline else output.change_score, uncertainty_score=output.uncertainty_score,
        referral_flag=referral, reason_codes=reasons, output=output, low_confidence_images=low_conf)


# ------------------------------------------------------------------ running a job
def _png(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data if imaging.sniff_mime(data) == imaging.PNG else None


async def _build_input(db: AsyncSession, lesion: Lesion, patient: Patient, usable, trigger: Visit):
    file_ids = [img.file_id for _, imgs in usable for img in imgs]
    stored = {f.id: f for f in (await db.scalars(select(StoredFile).where(StoredFile.id.in_(file_ids)))).all()}
    baseline_date = usable[0][0].visit_date
    visits, blobs = [], {}
    for visit, imgs in usable:
        visits.append(VisitInput(
            visit_id=str(visit.id), visit_date=visit.visit_date,
            days_since_baseline=(visit.visit_date - baseline_date).days, device_model=visit.device_model,
            illumination=visit.illumination, polarised=visit.polarised,
            images=[ImageInput(image_id=str(i.id), modality=i.modality, sha256=stored[i.file_id].sha256)
                    for i in imgs]))
        for img in imgs:
            data = await asyncio.to_thread(storage.decrypt_from_disk, stored[img.file_id])  # memory only
            blobs[str(img.id)] = (data, stored[img.file_id].mime_type)
    treatments = (await db.scalars(select(TreatmentEvent).where(
        TreatmentEvent.lesion_id == lesion.id, TreatmentEvent.treatment_date <= trigger.visit_date)
        .order_by(TreatmentEvent.treatment_date))).all()
    history = {k: v for k, v in (patient.medical_history or {}).items() if isinstance(v, bool)}  # never free text
    seq = LesionSequenceInput(
        lesion_ref=f"{patient.pseudonym_id}-{hashlib.sha256(str(lesion.id).encode()).hexdigest()[:6]}",
        visits=visits,
        clinical=ClinicalInput(age_band=age_band(patient.identity.date_of_birth), sex=patient.sex,
                               anatomical_site=lesion.anatomical_site, fitzpatrick_type=patient.fitzpatrick_type,
                               history=history),
        treatments=[TreatmentInput(treatment_type=t.treatment_type, treatment_date=t.treatment_date)
                    for t in treatments])
    return seq, blobs


async def _store_png(db: AsyncSession, hospital_id: uuid.UUID, data: bytes | None, name: str) -> uuid.UUID | None:
    if data is None:
        return None
    stored, _ = await files_svc.store(db, hospital_id=hospital_id, data=data, mime=imaging.PNG, filename=name,
                                      uploaded_by=None)
    return stored.id


async def analyse(db: AsyncSession, job: InferenceJob) -> Prediction:
    lesion = await db.get(Lesion, job.lesion_id)
    patient = await db.get(Patient, lesion.patient_id)
    model = await db.get(ModelVersion, job.model_version_id)
    trigger = await db.get(Visit, job.trigger_visit_id)
    usable = [(v, imgs) for v, imgs in await _usable_visits(db, lesion.id) if v.visit_date <= trigger.visit_date]
    if not usable:
        raise JobFailed("This lesion no longer has scans to analyse")

    seq, blobs = await _build_input(db, lesion, patient, usable, trigger)
    started = time.perf_counter()
    output, error = None, None
    try:
        output = await ml_client.infer(seq, blobs)
    except ml_client.ModelCallError as exc:
        error = str(exc)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    images = {str(i.id): i for _, imgs in usable for i in imgs}
    confirmed = {iid for iid, img in images.items() if img.mask_confirmed_by is not None}
    result = apply_safety_wrapper(output, error, model=model, visit_count=len(usable), confirmed_image_ids=confirmed)
    out = result.output

    raw = out.model_dump(mode="json", exclude={"difference_map_png_b64": True, "saliency_png_b64": True,
                                               "images": {"__all__": {"mask_png_b64"}}}) if out else {}
    if result.error:
        raw["error"] = result.error[:1000]
    prediction = Prediction(
        visit_id=trigger.id, lesion_id=lesion.id, hospital_id=lesion.hospital_id, job_id=job.id,
        model_version_id=model.id, is_baseline=result.is_baseline, risk_score=result.risk_score,
        risk_category=result.risk_category, change_score=result.change_score,
        uncertainty_score=result.uncertainty_score, referral_flag=result.referral_flag,
        reason_codes=result.reason_codes, modality_mask=out.modality_mask if out else {},
        treatment_response=out.treatment_response if out else None, raw_output=raw, inference_ms=elapsed_ms)
    db.add(prediction)
    await db.flush()

    if out is not None:
        visit_ids = {str(v.id) for v, _ in usable}
        db.add(Explanation(
            prediction_id=prediction.id,
            attention_weights={k: float(v) for k, v in out.attention_weights.items() if k in visit_ids},
            difference_map_file_id=await _store_png(db, lesion.hospital_id, _png(out.difference_map_png_b64),
                                                    f"difference_map_{prediction.id}.png"),
            saliency_file_id=await _store_png(db, lesion.hospital_id, _png(out.saliency_png_b64),
                                              f"saliency_{prediction.id}.png"),
            change_summary=out.change_summary, registration_warning=out.registration_warning,
            saliency_passed_check=out.saliency_passed_check))
        for res in out.images:
            img = images.get(res.image_id)
            if img is None or img.mask_confirmed_by is not None:  # never overwrite a doctor-confirmed mask
                continue
            mask_id = await _store_png(db, lesion.hospital_id, _png(res.mask_png_b64), f"mask_{img.id}.png")
            if mask_id is not None:
                img.mask_file_id = mask_id
            img.mask_confidence = res.mask_confidence
            img.registration_transform = res.registration_transform
            img.registration_quality = res.registration_quality

    await write_audit(db, "prediction.create", hospital_id=lesion.hospital_id, entity_type="prediction",
                      entity_id=prediction.id,
                      details={"job_id": str(job.id), "model": f"{model.name} {model.version}",
                               "is_mock": model.is_mock, "baseline": result.is_baseline,
                               "referral": result.referral_flag, "category": result.risk_category,
                               "reason_codes": result.reason_codes, "inference_ms": elapsed_ms,
                               **({"error": result.error[:300]} if result.error else {})})
    return prediction


class JobFailed(Exception):
    """A job that cannot produce any prediction (not a model error, which still yields a referral)."""


async def claim_next(db: AsyncSession) -> uuid.UUID | None:
    job = await db.scalar(select(InferenceJob).where(InferenceJob.status == "queued")
                          .order_by(InferenceJob.created_at).limit(1).with_for_update(skip_locked=True))
    if job is None:
        await db.rollback()
        return None
    job.status, job.started_at, job.attempts = "running", _now(), job.attempts + 1
    await db.commit()
    return job.id


async def requeue_stale(db: AsyncSession) -> int:
    """Jobs left 'running' by a worker that died: retry them, or fail them after the last attempt."""
    cutoff = _now() - timedelta(seconds=settings.job_stale_after_s)
    jobs = (await db.scalars(select(InferenceJob).where(InferenceJob.status == "running",
                                                        InferenceJob.started_at < cutoff)
                             .with_for_update(skip_locked=True))).all()
    for job in jobs:
        if job.attempts >= settings.job_max_attempts:
            job.status, job.finished_at = "failed", _now()
            job.error = "The analysis did not finish after several attempts"
        else:
            job.status = "queued"
    await db.commit()
    return len(jobs)


async def run_job(db: AsyncSession, job_id: uuid.UUID) -> None:
    job = await db.get(InferenceJob, job_id)
    try:
        prediction = await analyse(db, job)
        job.status, job.finished_at, job.prediction_id = "succeeded", _now(), prediction.id
        job.error = (prediction.raw_output or {}).get("error")
        await db.commit()
        log.info("Job %s done: prediction %s", job_id, prediction.id)
    except Exception as exc:  # noqa: BLE001 - record the failure on the job, never crash the worker
        await db.rollback()
        log.exception("Job %s failed", job_id)
        job = await db.get(InferenceJob, job_id)
        permanent = isinstance(exc, (JobFailed, storage.StorageError))
        if permanent or job.attempts >= settings.job_max_attempts:
            job.status, job.finished_at = "failed", _now()
            job.error = str(exc)[:500] if permanent else "The analysis failed repeatedly; see the server log"
        else:
            job.status = "queued"
        await db.commit()
