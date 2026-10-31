"""Doctor review of AI results (human in the loop), the review worklist, lesion outlines and treatment events."""
import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import Request, UploadFile
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import (ClinicianReview, Image, Lesion, ModelVersion, Patient, PatientIdentity, Prediction,
                        TreatmentEvent, User, Visit)
from app.schemas.common import Page
from app.schemas.records import ImageOut
from app.schemas.review import (HISTOPATHOLOGY_TYPES, ReviewIn, ReviewOut, TreatmentCreate, TreatmentOut,
                                TreatmentUpdate, WorklistItem)
from app.services import files as files_svc
from app.services import imaging
from app.services.audit import write_audit
from app.services.predictions import latest_review, reviews_for
from app.services.records import image_out, lesion_in_scope


async def _prediction(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> Prediction:
    pred = await db.get(Prediction, prediction_id)
    if pred is None or pred.hospital_id != scope.hospital_id:
        raise not_found("Prediction")
    return pred


async def review_prediction(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID, data: ReviewIn, actor: User,
                            request: Request) -> ReviewOut:
    pred = await _prediction(db, scope, prediction_id)
    ai_category = None if (pred.referral_flag or pred.is_baseline) else pred.risk_category
    decision = "confirmed" if ai_category is not None and data.final_category == ai_category else "overridden"
    if decision == "overridden" and len((data.reason or "").strip()) < 3:
        raise AppError(422, "REASON_REQUIRED",
                       "Give a reason: one is required when you change the AI category or the case was referred")
    review = ClinicianReview(prediction_id=pred.id, reviewer_id=actor.id, decision=decision,
                             final_category=data.final_category, reason=data.reason)
    db.add(review)
    await db.flush()
    await write_audit(db, "prediction.review", user=actor, entity_type="prediction", entity_id=pred.id,
                      details={"review_id": str(review.id), "decision": decision,
                               "final_category": data.final_category, "ai_category": ai_category,
                               "referral": pred.referral_flag}, request=request)
    await db.commit()
    return await latest_review(db, pred.id)


async def list_reviews(db: AsyncSession, scope: Scope, prediction_id: uuid.UUID) -> list[ReviewOut]:
    pred = await _prediction(db, scope, prediction_id)
    return await reviews_for(db, pred.id)


SEVERITY = case({"specialist_referral": 3, "shortened_interval": 2, "routine_monitoring": 1},
                value=cast(Prediction.risk_category, String), else_=0)


async def worklist(db: AsyncSession, scope: Scope, *, state: str, page: int, page_size: int) -> Page[WorklistItem]:
    """Each lesion's newest result. Pending: unreviewed and either scored or referred (referrals first)."""
    latest = (select(Prediction.id).where(Prediction.hospital_id == scope.hospital_id)
              .distinct(Prediction.lesion_id).order_by(Prediction.lesion_id, Prediction.created_at.desc()))
    last_review = (select(ClinicianReview.prediction_id, func.max(ClinicianReview.created_at).label("reviewed_at"))
                   .group_by(ClinicianReview.prediction_id).subquery())
    stmt = (select(Prediction, Lesion.label, Lesion.anatomical_site, Patient.id.label("patient_id"),
                   PatientIdentity.full_name, Patient.mrn, Visit.visit_date, ModelVersion.is_mock,
                   last_review.c.reviewed_at)
            .join(Lesion, Prediction.lesion_id == Lesion.id)
            .join(Patient, Lesion.patient_id == Patient.id)
            .join(PatientIdentity, PatientIdentity.patient_id == Patient.id)
            .join(Visit, Prediction.visit_id == Visit.id)
            .join(ModelVersion, Prediction.model_version_id == ModelVersion.id)
            .outerjoin(last_review, last_review.c.prediction_id == Prediction.id)
            .where(Prediction.id.in_(latest)))
    if state == "pending":
        stmt = stmt.where(last_review.c.reviewed_at.is_(None),
                          (Prediction.is_baseline.is_(False)) | Prediction.referral_flag.is_(True))
        order = (Prediction.referral_flag.desc(), SEVERITY.desc(), Prediction.created_at)
    else:
        stmt = stmt.where(last_review.c.reviewed_at.is_not(None))
        order = (last_review.c.reviewed_at.desc(),)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size))).all()

    items = []
    for row in rows:
        pred = row.Prediction
        review = await latest_review(db, pred.id) if row.reviewed_at else None
        items.append(WorklistItem(
            prediction_id=pred.id, lesion_id=pred.lesion_id, lesion_label=row.label,
            anatomical_site=row.anatomical_site, patient_id=row.patient_id, patient_name=row.full_name,
            mrn=row.mrn, visit_date=row.visit_date, is_baseline=pred.is_baseline, referral_flag=pred.referral_flag,
            reason_codes=list(pred.reason_codes or []), risk_category=pred.risk_category,
            risk_score=float(pred.risk_score) if pred.risk_score is not None else None, is_mock=row.is_mock,
            analysed_at=pred.created_at, final_category=review.final_category if review else None,
            reviewed_at=review.created_at if review else None, reviewer_name=review.reviewer_name if review else None))
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


async def set_mask(db: AsyncSession, scope: Scope, image_id: uuid.UUID, upload: UploadFile | None, confirm: bool,
                   actor: User, request: Request) -> ImageOut:
    """Confirms the AI outline, or stores a doctor-drawn one. Either way the outline counts as confirmed, so a low
    segmentation confidence no longer forces a referral, and re-analysis never overwrites it."""
    img = await db.get(Image, image_id)
    if img is None or img.hospital_id != scope.hospital_id:
        raise not_found("Image")
    if upload is None:
        if not confirm:
            raise AppError(422, "VALIDATION_ERROR", "Send a corrected outline, or confirm=true")
        if img.mask_file_id is None:
            raise AppError(409, "NO_MASK", "There is no outline to confirm yet. Run an analysis or draw one.")
        action = "confirmed"
    else:
        try:
            raw = await files_svc.read_upload(upload)
            if imaging.sniff_mime(raw) != imaging.PNG:
                raise imaging.UploadRejected("The outline must be a PNG image")
            mask = await asyncio.to_thread(imaging.normalise_mask, raw, img.width, img.height)
        except imaging.UploadRejected as exc:
            raise AppError(422, "INVALID_FILE", str(exc))
        stored, _ = await files_svc.store(db, hospital_id=img.hospital_id, data=mask, mime=imaging.PNG,
                                          filename=f"mask_{img.id}_corrected.png", uploaded_by=actor.id)
        img.mask_file_id, img.mask_confidence = stored.id, 1.0
        action = "corrected"
    img.mask_confirmed_by = actor.id
    await write_audit(db, "mask.update", user=actor, entity_type="image", entity_id=img.id,
                      details={"action": action, "mask_file_id": str(img.mask_file_id)}, request=request)
    await db.commit()
    return image_out(img, show_ai=True)


def _treatment_out(t: TreatmentEvent) -> TreatmentOut:
    return TreatmentOut(id=t.id, treatment_type=t.treatment_type, treatment_date=t.treatment_date,
                        response_category=t.response_category, notes=t.notes, histopathology=t.histopathology,
                        histopathology_recorded_at=t.histopathology_recorded_at, created_at=t.created_at)


def _check_histopathology(treatment_type: str, value: str | None) -> None:
    if value is not None and treatment_type not in HISTOPATHOLOGY_TYPES:
        raise AppError(422, "HISTOPATHOLOGY_NOT_APPLICABLE",
                       "A histopathology result can only be recorded for a biopsy or an excision")


async def list_treatments(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID) -> list[TreatmentOut]:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    rows = (await db.scalars(select(TreatmentEvent).where(TreatmentEvent.lesion_id == lesion.id)
                             .order_by(TreatmentEvent.treatment_date))).all()
    return [_treatment_out(t) for t in rows]


async def create_treatment(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID, data: TreatmentCreate, actor: User,
                           request: Request) -> TreatmentOut:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    patient = await db.get(Patient, lesion.patient_id)
    if data.treatment_date < patient.identity.date_of_birth:
        raise AppError(422, "VALIDATION_ERROR", "Treatment date is before the patient's date of birth")
    _check_histopathology(data.treatment_type, data.histopathology)
    event = TreatmentEvent(lesion_id=lesion.id, hospital_id=lesion.hospital_id, treatment_type=data.treatment_type,
                           treatment_date=data.treatment_date, notes=data.notes, created_by=actor.id)
    if data.histopathology is not None:
        event.histopathology, event.histopathology_recorded_by = data.histopathology, actor.id
        event.histopathology_recorded_at = datetime.now(timezone.utc)
    db.add(event)
    await db.flush()
    await write_audit(db, "treatment.create", user=actor, entity_type="treatment_event", entity_id=event.id,
                      details={"lesion_id": str(lesion.id), "treatment_type": data.treatment_type,
                               "histopathology_recorded": data.histopathology is not None}, request=request)
    await db.commit()
    return _treatment_out(event)


async def update_treatment(db: AsyncSession, scope: Scope, event_id: uuid.UUID, data: TreatmentUpdate, actor: User,
                           request: Request) -> TreatmentOut:
    event = await db.get(TreatmentEvent, event_id)
    if event is None or event.hospital_id != scope.hospital_id:
        raise not_found("Treatment")
    _check_histopathology(event.treatment_type, data.histopathology)
    if event.histopathology != data.histopathology:
        event.histopathology = data.histopathology
        event.histopathology_recorded_by = actor.id if data.histopathology else None
        event.histopathology_recorded_at = datetime.now(timezone.utc) if data.histopathology else None
        # Field names only (like patient changes): the result itself stays in the clinical record.
        await write_audit(db, "treatment.update", user=actor, entity_type="treatment_event", entity_id=event.id,
                          details={"lesion_id": str(event.lesion_id), "fields": ["histopathology"]}, request=request)
        await db.commit()
    return _treatment_out(event)
