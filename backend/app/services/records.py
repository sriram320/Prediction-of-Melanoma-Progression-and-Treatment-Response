"""Lesions, visits, the lesion timeline and scan uploads (M1 acquisition + M2 quality pre-check)."""
import asyncio
import uuid
from collections import defaultdict

from fastapi import Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import Image, Lesion, Patient, TreatmentEvent, User, Visit
from app.schemas.records import (ImageOut, LesionCreate, LesionOut, PatientBrief, StaffTimelineOut, TimelineOut,
                                 UploadResult, VisitCreate, VisitExclude, VisitOut)
from app.services import files as files_svc
from app.services import predictions as predictions_svc
from app.services import imaging
from app.services.audit import write_audit
from app.services.patients import age_band, patient_in_scope


async def lesion_in_scope(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID) -> Lesion:
    lesion = await db.get(Lesion, lesion_id)
    if (lesion is None or lesion.hospital_id != scope.hospital_id
            or (scope.is_patient and lesion.patient_id != scope.patient_id)):
        raise not_found("Lesion")
    return lesion


async def visit_in_scope(db: AsyncSession, scope: Scope, visit_id: uuid.UUID) -> tuple[Visit, Lesion]:
    visit = await db.get(Visit, visit_id)
    if visit is None or visit.hospital_id != scope.hospital_id:
        raise not_found("Visit")
    lesion = await lesion_in_scope(db, scope, visit.lesion_id)
    return visit, lesion


async def _lesion_summaries(db: AsyncSession, lesions: list[Lesion]) -> list[LesionOut]:
    ids = [lesion.id for lesion in lesions]
    stats = {row.lesion_id: row for row in (await db.execute(
        select(Visit.lesion_id, func.count(Visit.id).label("n"), func.min(Visit.visit_date).label("first"),
               func.max(Visit.visit_date).label("last"))
        .where(Visit.lesion_id.in_(ids)).group_by(Visit.lesion_id))).all()} if ids else {}
    latest: dict[uuid.UUID, uuid.UUID] = {}
    if ids:
        rows = (await db.execute(
            select(Visit.lesion_id, Image.file_id).join(Image, Image.visit_id == Visit.id)
            .where(Visit.lesion_id.in_(ids), Visit.excluded.is_(False))
            .order_by(Visit.visit_date.desc(), (Image.modality != "dermoscopic"), Image.created_at))).all()
        for lesion_id, file_id in rows:
            latest.setdefault(lesion_id, file_id)
    out = []
    for lesion in lesions:
        s = stats.get(lesion.id)
        out.append(LesionOut(
            id=lesion.id, patient_id=lesion.patient_id, label=lesion.label, anatomical_site=lesion.anatomical_site,
            status=lesion.status, created_at=lesion.created_at, visit_count=s.n if s else 0,
            first_visit_date=s.first if s else None, last_visit_date=s.last if s else None,
            latest_image_file_id=latest.get(lesion.id)))
    return out


async def list_lesions(db: AsyncSession, scope: Scope, patient_id: uuid.UUID) -> list[LesionOut]:
    await patient_in_scope(db, scope, patient_id)
    lesions = (await db.scalars(select(Lesion).where(Lesion.patient_id == patient_id)
                                .order_by(Lesion.created_at))).all()
    return await _lesion_summaries(db, list(lesions))


async def create_lesion(db: AsyncSession, scope: Scope, patient_id: uuid.UUID, data: LesionCreate, actor: User,
                        request: Request) -> LesionOut:
    patient = await patient_in_scope(db, scope, patient_id)
    taken = await db.scalar(select(Lesion.id).where(Lesion.patient_id == patient.id,
                                                    func.lower(Lesion.label) == data.label.lower()).limit(1))
    if taken is not None:
        raise AppError(409, "LABEL_TAKEN", "This patient already has a lesion with that label")
    lesion = Lesion(patient_id=patient.id, hospital_id=patient.hospital_id, label=data.label,
                    anatomical_site=data.anatomical_site)
    db.add(lesion)
    await db.flush()
    await write_audit(db, "lesion.create", user=actor, entity_type="lesion", entity_id=lesion.id,
                      details={"patient_id": str(patient.id), "anatomical_site": data.anatomical_site},
                      request=request)
    await db.commit()
    return (await _lesion_summaries(db, [lesion]))[0]


def _visit_out(visit: Visit, images: list[Image]) -> VisitOut:
    return VisitOut(
        id=visit.id, visit_date=visit.visit_date, device_model=visit.device_model, illumination=visit.illumination,
        polarised=visit.polarised, quality_score=visit.quality_score, quality_flags=visit.quality_flags or [],
        excluded=visit.excluded, notes=visit.notes, created_at=visit.created_at,
        images=[ImageOut.model_validate(i) for i in images])


async def timeline(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID) -> TimelineOut:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    patient = await db.get(Patient, lesion.patient_id)
    visits = (await db.scalars(select(Visit).where(Visit.lesion_id == lesion.id)
                               .order_by(Visit.visit_date, Visit.created_at))).all()
    by_visit: dict[uuid.UUID, list[Image]] = defaultdict(list)
    if visits:
        for img in (await db.scalars(select(Image).where(Image.visit_id.in_([v.id for v in visits]))
                                     .order_by(Image.created_at))).all():
            by_visit[img.visit_id].append(img)
    treatments = (await db.scalars(select(TreatmentEvent).where(TreatmentEvent.lesion_id == lesion.id)
                                   .order_by(TreatmentEvent.treatment_date))).all()
    ident = patient.identity
    fields = dict(
        lesion=(await _lesion_summaries(db, [lesion]))[0],
        patient=PatientBrief(id=patient.id, mrn=patient.mrn, pseudonym_id=patient.pseudonym_id,
                             full_name=ident.full_name, sex=patient.sex, age_band=age_band(ident.date_of_birth),
                             fitzpatrick_type=patient.fitzpatrick_type),
        visits=[_visit_out(v, by_visit[v.id]) for v in visits],
        analysable_visit_count=sum(1 for v in visits if not v.excluded and by_visit[v.id]),
        treatment_events=[{"id": str(t.id), "treatment_type": t.treatment_type,
                           "treatment_date": t.treatment_date.isoformat(), "response_category": t.response_category,
                           "notes": t.notes} for t in treatments],
        latest_job=await predictions_svc.latest_job(db, lesion.id),
    )
    # Technicians never receive AI results (permission matrix); the key is left out entirely.
    if scope.role in predictions_svc.AI_RESULT_ROLES:
        return StaffTimelineOut(**fields, latest_prediction=await predictions_svc.latest_prediction(db, lesion.id))
    return TimelineOut(**fields)


async def create_visit(db: AsyncSession, scope: Scope, lesion_id: uuid.UUID, data: VisitCreate, actor: User,
                       request: Request) -> VisitOut:
    lesion = await lesion_in_scope(db, scope, lesion_id)
    patient = await db.get(Patient, lesion.patient_id)
    if data.visit_date < patient.identity.date_of_birth:
        raise AppError(422, "VALIDATION_ERROR", "Visit date is before the patient's date of birth")
    clash = await db.scalar(select(Visit.id).where(Visit.lesion_id == lesion.id,
                                                   Visit.visit_date == data.visit_date).limit(1))
    if clash is not None:
        raise AppError(409, "VISIT_DATE_TAKEN",
                       "This lesion already has a visit on that date; add the images to that visit instead")
    visit = Visit(lesion_id=lesion.id, hospital_id=lesion.hospital_id, visit_date=data.visit_date,
                  device_model=data.device_model, illumination=data.illumination, polarised=data.polarised,
                  notes=data.notes, created_by=actor.id)
    db.add(visit)
    await db.flush()
    lesion.first_seen_visit_id = await db.scalar(
        select(Visit.id).where(Visit.lesion_id == lesion.id).order_by(Visit.visit_date, Visit.created_at).limit(1))
    await write_audit(db, "visit.create", user=actor, entity_type="visit", entity_id=visit.id,
                      details={"lesion_id": str(lesion.id), "visit_date": data.visit_date.isoformat()},
                      request=request)
    await db.commit()
    return _visit_out(visit, [])


async def set_visit_excluded(db: AsyncSession, scope: Scope, visit_id: uuid.UUID, data: VisitExclude, actor: User,
                             request: Request) -> VisitOut:
    visit, _ = await visit_in_scope(db, scope, visit_id)
    if visit.excluded != data.excluded:
        visit.excluded = data.excluded
        await write_audit(db, "visit.exclude", user=actor, entity_type="visit", entity_id=visit.id,
                          details={"excluded": data.excluded, "reason": data.reason}, request=request)
        await db.commit()
    images = (await db.scalars(select(Image).where(Image.visit_id == visit.id).order_by(Image.created_at))).all()
    return _visit_out(visit, list(images))


async def _refresh_visit_quality(db: AsyncSession, visit: Visit) -> None:
    rows = (await db.execute(select(Image.quality_score, Image.quality_flags)
                             .where(Image.visit_id == visit.id))).all()
    scores = [r.quality_score for r in rows if r.quality_score is not None]
    visit.quality_score = min(scores) if scores else None
    visit.quality_flags = sorted({f for r in rows for f in (r.quality_flags or [])})


async def upload_images(db: AsyncSession, scope: Scope, visit_id: uuid.UUID, uploads: list[UploadFile],
                        modality: str, actor: User, request: Request) -> list[UploadResult]:
    visit, _ = await visit_in_scope(db, scope, visit_id)
    if not uploads:
        raise AppError(422, "VALIDATION_ERROR", "Choose at least one file")
    if len(uploads) > settings.max_files_per_upload:
        raise AppError(422, "TOO_MANY_FILES", f"Upload at most {settings.max_files_per_upload} files at a time")

    results: list[UploadResult] = []
    for upload in uploads:
        name = files_svc.clean_filename(upload.filename)
        try:
            raw = await files_svc.read_upload(upload)
            mime = imaging.sniff_mime(raw)
            if mime not in imaging.SCAN_TYPES:
                raise imaging.UploadRejected("Not a supported scan type (use JPEG, PNG, TIFF or DICOM)")
            prepared = await asyncio.to_thread(imaging.prepare_scan, raw, mime)
        except imaging.UploadRejected as exc:
            results.append(UploadResult(filename=name, error=str(exc)))
            continue

        stored, duplicate = await files_svc.store(db, hospital_id=visit.hospital_id, data=prepared.data,
                                                  mime=prepared.mime, filename=name, uploaded_by=actor.id)
        if duplicate:
            existing = (await db.execute(
                select(Image.id, Visit.id.label("visit_id"), Visit.visit_date).join(Visit, Image.visit_id == Visit.id)
                .where(Image.file_id == stored.id).limit(1))).first()
            if existing is not None:
                where = "this visit" if existing.visit_id == visit.id else f"the visit of {existing.visit_date:%d %b %Y}"
                results.append(UploadResult(
                    filename=name, image_id=existing.id, file_id=stored.id, duplicate=True,
                    duplicate_visit_date=existing.visit_date,
                    error=f"This exact image is already stored for {where}, so it was not added again"))
                continue

        source_id = None
        if prepared.source is not None:
            source, _ = await files_svc.store(db, hospital_id=visit.hospital_id, data=prepared.source,
                                              mime=imaging.DICOM, filename=name, uploaded_by=actor.id)
            source_id = source.id
        image = Image(visit_id=visit.id, hospital_id=visit.hospital_id, modality=modality, file_id=stored.id,
                      source_file_id=source_id, width=prepared.width, height=prepared.height,
                      quality_score=prepared.quality_score, quality_flags=prepared.quality_flags)
        db.add(image)
        await db.flush()
        if prepared.device_model and not visit.device_model:
            visit.device_model = prepared.device_model
        await write_audit(db, "file.upload", user=actor, entity_type="image", entity_id=image.id,
                          details={"visit_id": str(visit.id), "file_id": str(stored.id), "mime": prepared.mime,
                                   "bytes": len(prepared.data), "quality_flags": prepared.quality_flags},
                          request=request)
        results.append(UploadResult(filename=name, image_id=image.id, file_id=stored.id,
                                    quality_score=prepared.quality_score, quality_flags=prepared.quality_flags))

    await _refresh_visit_quality(db, visit)
    await db.commit()
    return results
