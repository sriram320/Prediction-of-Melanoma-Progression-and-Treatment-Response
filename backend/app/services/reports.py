"""Reports: draft -> signed -> released -> amended (superseded by a newer released version).

Rules:
- Only doctors draft, edit, sign and amend; doctors and hospital admins release.
- A report on an AI result needs the doctor's review first; its category is the reviewed category.
- Signing renders the patient and clinician PDFs (encrypted) and locks the report.
- Patients see released reports only, and only the patient copy (invariant 4). Technicians see released reports
  and the patient copy only (the clinician copy holds AI results).
"""
import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import storage
from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import (Explanation, Hospital, Image, Lesion, ModelVersion, Patient, Prediction, Report, StoredFile,
                        User, Visit)
from app.schemas.common import Page
from app.schemas.reports import MyReport, ReportCreate, ReportOut, ReportUpdate
from app.services import files as files_svc
from app.services import imaging
from app.services.audit import write_audit
from app.services.predictions import AI_RESULT_ROLES, latest_review, model_info
from app.services.records import lesion_in_scope
from app.services.report_pdf import ReportContext, render

EDITABLE = ("draft", "pending_review")
HAS_PDF = ("signed", "released", "amended")

SUMMARY_TEMPLATES = {
    "routine_monitoring": ("We compared photos of this spot taken between {first} and {last}. Your doctor found no "
                           "changes that need action now. Please keep your routine skin checks, and tell us if the "
                           "spot changes in size, shape or colour, itches or bleeds."),
    "shortened_interval": ("We compared photos of this spot taken between {first} and {last}. Your doctor would like "
                           "to see this spot again sooner than usual to keep a closer eye on it. This is a precaution."),
    "specialist_referral": ("We compared photos of this spot taken between {first} and {last}. Your doctor recommends "
                            "that a skin specialist examines this spot. This does not mean it is cancer; it means it "
                            "needs a closer look."),
}
RECOMMENDATIONS = {
    "routine_monitoring": "Routine skin check in 12 months",
    "shortened_interval": "Follow-up visit in 3 months",
    "specialist_referral": "See a dermatologist within 2 weeks",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _report(db: AsyncSession, scope: Scope, report_id: uuid.UUID) -> Report:
    report = await db.get(Report, report_id)
    if report is None or report.hospital_id != scope.hospital_id:
        raise not_found("Report")
    if scope.role == "technician" and report.status != "released":
        raise not_found("Report")
    return report


async def report_out(db: AsyncSession, scope: Scope, r: Report) -> ReportOut:
    patient = await db.get(Patient, r.patient_id)
    lesion = await db.get(Lesion, r.lesion_id) if r.lesion_id else None
    names = dict((await db.execute(select(User.id, User.full_name).where(
        User.id.in_([u for u in (r.created_by, r.signed_by) if u])))).all())
    pred = await db.get(Prediction, r.prediction_id) if r.prediction_id else None
    supersedes = await db.get(Report, r.supersedes_id) if r.supersedes_id else None
    superseded_by = await db.scalar(select(Report.id).where(Report.supersedes_id == r.id).limit(1))
    clinical = scope.role in AI_RESULT_ROLES
    return ReportOut(
        id=r.id, report_number=r.report_number, version=r.version, status=r.status, patient_id=r.patient_id,
        patient_name=patient.identity.full_name, mrn=patient.mrn, lesion_id=r.lesion_id,
        lesion_label=lesion.label if lesion else None, anatomical_site=lesion.anatomical_site if lesion else None,
        prediction_id=r.prediction_id if clinical else None, final_category=r.final_category,
        category_from_review=r.prediction_id is not None, patient_summary=r.patient_summary,
        recommendation=r.recommendation, doctor_notes=r.doctor_notes if clinical else None,
        model=await model_info(db, pred.model_version_id) if (pred and clinical) else None,
        created_by_name=names.get(r.created_by), signed_by_name=names.get(r.signed_by), signed_at=r.signed_at,
        released_at=r.released_at, created_at=r.created_at, supersedes_id=r.supersedes_id,
        supersedes_number=supersedes.report_number if supersedes else None, superseded_by_id=superseded_by,
        has_pdf=r.pdf_file_id is not None)


async def _visits_with_images(db: AsyncSession, lesion_id: uuid.UUID, up_to: date | None):
    stmt = select(Visit).where(Visit.lesion_id == lesion_id, Visit.excluded.is_(False))
    if up_to:
        stmt = stmt.where(Visit.visit_date <= up_to)
    visits = (await db.scalars(stmt.order_by(Visit.visit_date))).all()
    out = []
    for v in visits:
        imgs = (await db.scalars(select(Image).where(Image.visit_id == v.id).order_by(Image.created_at))).all()
        if imgs:
            out.append((v, next((i for i in imgs if i.modality == "dermoscopic"), imgs[0])))
    return out


async def create_report(db: AsyncSession, scope: Scope, data: ReportCreate, actor: User,
                        request: Request) -> ReportOut:
    lesion = await lesion_in_scope(db, scope, data.lesion_id)
    if data.prediction_id is not None:
        pred = await db.get(Prediction, data.prediction_id)
        if pred is None or pred.lesion_id != lesion.id:
            raise AppError(422, "VALIDATION_ERROR", "prediction_id: that result does not belong to this lesion")
    else:
        pred = await db.scalar(select(Prediction).where(Prediction.lesion_id == lesion.id)
                               .order_by(Prediction.created_at.desc()).limit(1))
    open_draft = await db.scalar(select(Report.id).where(
        Report.lesion_id == lesion.id, Report.status.in_(EDITABLE), Report.supersedes_id.is_(None),
        (Report.prediction_id == pred.id) if pred else Report.prediction_id.is_(None)).limit(1))
    if open_draft is not None:
        raise AppError(409, "DRAFT_EXISTS", "A draft report for this result already exists; open it instead")

    review = await latest_review(db, pred.id) if pred else None
    category = review.final_category if review else None
    visits = await _visits_with_images(db, lesion.id, None)
    notes = None
    if pred is not None:
        exp = await db.scalar(select(Explanation).where(Explanation.prediction_id == pred.id))
        if exp and exp.change_summary:
            notes = "AI change summary:\n" + "\n".join(f"- {s}" for s in exp.change_summary)
    summary = None
    if category and visits:
        summary = SUMMARY_TEMPLATES[category].format(first=f"{visits[0][0].visit_date:%d %b %Y}",
                                                     last=f"{visits[-1][0].visit_date:%d %b %Y}")
    number = await db.scalar(text("SELECT nextval('report_number_seq')"))
    report = Report(report_number=f"MT-{_now():%Y}-{number:06d}", patient_id=lesion.patient_id,
                    hospital_id=lesion.hospital_id, lesion_id=lesion.id, prediction_id=pred.id if pred else None,
                    final_category=category, patient_summary=summary,
                    recommendation=RECOMMENDATIONS.get(category), doctor_notes=notes, created_by=actor.id)
    db.add(report)
    await db.flush()
    await write_audit(db, "report.create", user=actor, entity_type="report", entity_id=report.id,
                      details={"report_number": report.report_number, "lesion_id": str(lesion.id),
                               "prediction_id": str(pred.id) if pred else None}, request=request)
    await db.commit()
    return await report_out(db, scope, report)


async def list_reports(db: AsyncSession, scope: Scope, *, patient_id: uuid.UUID | None, lesion_id: uuid.UUID | None,
                       status: str | None, page: int, page_size: int) -> Page[ReportOut]:
    stmt = select(Report).where(Report.hospital_id == scope.hospital_id)
    if patient_id:
        stmt = stmt.where(Report.patient_id == patient_id)
    if lesion_id:
        stmt = stmt.where(Report.lesion_id == lesion_id)
    if scope.role == "technician":
        stmt = stmt.where(Report.status == "released")
    elif status:
        stmt = stmt.where(Report.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(Report.created_at.desc()).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    return Page(items=[await report_out(db, scope, r) for r in rows], total=total or 0, page=page,
                page_size=page_size)


async def get_report(db: AsyncSession, scope: Scope, report_id: uuid.UUID) -> ReportOut:
    return await report_out(db, scope, await _report(db, scope, report_id))


async def update_report(db: AsyncSession, scope: Scope, report_id: uuid.UUID, data: ReportUpdate, actor: User,
                        request: Request) -> ReportOut:
    report = await _report(db, scope, report_id)
    if report.status not in EDITABLE:
        raise AppError(409, "REPORT_LOCKED", "A signed report cannot be edited; create an amendment instead")
    sent = data.model_fields_set
    if "final_category" in sent and report.prediction_id is not None:
        raise AppError(422, "CATEGORY_FROM_REVIEW",
                       "This report's category comes from your review of the AI result; change the review instead")
    for name in ("final_category", "patient_summary", "recommendation", "doctor_notes"):
        if name in sent:
            setattr(report, name, getattr(data, name))
    await db.commit()
    return await report_out(db, scope, report)


async def _context(db: AsyncSession, report: Report, signer: User, signed_at: datetime) -> ReportContext:
    patient = await db.get(Patient, report.patient_id)
    hospital = await db.get(Hospital, report.hospital_id)
    lesion = await db.get(Lesion, report.lesion_id) if report.lesion_id else None
    pred = await db.get(Prediction, report.prediction_id) if report.prediction_id else None
    supersedes = await db.get(Report, report.supersedes_id) if report.supersedes_id else None
    ctx = ReportContext(
        hospital_name=hospital.name, hospital_address=hospital.address, report_number=report.report_number,
        version=report.version, supersedes_number=supersedes.report_number if supersedes else None,
        patient_name=patient.identity.full_name, mrn=patient.mrn, date_of_birth=patient.identity.date_of_birth,
        lesion_label=lesion.label if lesion else None, anatomical_site=lesion.anatomical_site if lesion else None,
        final_category=report.final_category, patient_summary=report.patient_summary,
        recommendation=report.recommendation, doctor_notes=report.doctor_notes, signed_by=signer.full_name,
        signed_by_registration=signer.registration_no, signed_at=signed_at)
    if lesion is not None:
        up_to = (await db.get(Visit, pred.visit_id)).visit_date if pred else None
        shown = (await _visits_with_images(db, lesion.id, up_to))[-6:]
        files = {f.id: f for f in (await db.scalars(select(StoredFile).where(
            StoredFile.id.in_([img.file_id for _, img in shown])))).all()}
        for visit, img in shown:
            data = await asyncio.to_thread(storage.decrypt_from_disk, files[img.file_id])
            ctx.photos.append((visit.visit_date, await asyncio.to_thread(imaging.make_thumbnail, data, 512)))
    if pred is not None:
        model = await db.get(ModelVersion, pred.model_version_id)
        review = await latest_review(db, pred.id)
        exp = await db.scalar(select(Explanation).where(Explanation.prediction_id == pred.id))
        ctx.model_name, ctx.model_version, ctx.is_mock = model.name, model.version, model.is_mock
        ctx.ai_category, ctx.referral_flag, ctx.is_baseline = pred.risk_category, pred.referral_flag, pred.is_baseline
        ctx.risk_score = float(pred.risk_score) if pred.risk_score is not None else None
        ctx.uncertainty_score = float(pred.uncertainty_score) if pred.uncertainty_score is not None else None
        ctx.reason_codes = list(pred.reason_codes or [])
        if review:
            ctx.review_decision, ctx.review_reason = review.decision, review.reason
        if exp is not None:
            ctx.change_summary = list(exp.change_summary or [])
            if exp.difference_map_file_id:
                stored = await db.get(StoredFile, exp.difference_map_file_id)
                ctx.difference_map_png = await asyncio.to_thread(storage.decrypt_from_disk, stored)
    else:
        active = await db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
        ctx.is_mock = bool(active and active.is_mock)  # the platform is still in mock mode: keep the watermark
    return ctx


async def sign_report(db: AsyncSession, scope: Scope, report_id: uuid.UUID, actor: User,
                      request: Request) -> ReportOut:
    report = await _report(db, scope, report_id)
    if report.status not in EDITABLE:
        raise AppError(409, "REPORT_LOCKED", "This report is already signed")
    if report.prediction_id is not None:
        review = await latest_review(db, report.prediction_id)
        if review is None:
            raise AppError(409, "REVIEW_REQUIRED", "Confirm or override the AI result before signing the report")
        report.final_category = review.final_category
    missing = [label for label, value in (("category", report.final_category), ("summary", report.patient_summary),
                                          ("recommendation", report.recommendation)) if not value]
    if missing:
        raise AppError(422, "INCOMPLETE_REPORT", f"Add the {', '.join(missing)} before signing")

    signed_at = _now()
    ctx = await _context(db, report, actor, signed_at)
    for variant in ("patient", "clinician"):
        pdf = await asyncio.to_thread(render, ctx, variant)
        stored, _ = await files_svc.store(db, hospital_id=report.hospital_id, data=pdf, mime=imaging.PDF,
                                          filename=f"{report.report_number}-{variant}.pdf", uploaded_by=actor.id)
        if variant == "patient":
            report.pdf_file_id = stored.id
        else:
            report.clinician_pdf_file_id = stored.id
    report.status, report.signed_by, report.signed_at = "signed", actor.id, signed_at
    await write_audit(db, "report.sign", user=actor, entity_type="report", entity_id=report.id,
                      details={"report_number": report.report_number, "version": report.version,
                               "final_category": report.final_category}, request=request)
    await db.commit()
    return await report_out(db, scope, report)


async def release_report(db: AsyncSession, scope: Scope, report_id: uuid.UUID, actor: User,
                         request: Request) -> ReportOut:
    report = await _report(db, scope, report_id)
    if report.status != "signed":
        raise AppError(409, "NOT_SIGNED" if report.status in EDITABLE else "ALREADY_RELEASED",
                       "Only a signed, unreleased report can be released")
    report.status, report.released_at = "released", _now()
    if report.supersedes_id:
        old = await db.get(Report, report.supersedes_id)
        if old is not None and old.status in ("signed", "released"):
            old.status = "amended"  # the patient now sees only the new version
    await write_audit(db, "report.release", user=actor, entity_type="report", entity_id=report.id,
                      details={"report_number": report.report_number}, request=request)
    await db.commit()
    return await report_out(db, scope, report)


async def amend_report(db: AsyncSession, scope: Scope, report_id: uuid.UUID, actor: User,
                       request: Request) -> ReportOut:
    old = await _report(db, scope, report_id)
    if old.status not in ("signed", "released"):
        raise AppError(409, "NOT_SIGNED", "Only a signed or released report can be amended")
    if await db.scalar(select(Report.id).where(Report.supersedes_id == old.id).limit(1)) is not None:
        raise AppError(409, "AMENDMENT_EXISTS", "This report already has an amendment")
    root = old.report_number.split("-V")[0]
    new = Report(report_number=f"{root}-V{old.version + 1}", patient_id=old.patient_id, hospital_id=old.hospital_id,
                 lesion_id=old.lesion_id, prediction_id=old.prediction_id, final_category=old.final_category,
                 patient_summary=old.patient_summary, recommendation=old.recommendation,
                 doctor_notes=old.doctor_notes, version=old.version + 1, supersedes_id=old.id, created_by=actor.id)
    db.add(new)
    await db.flush()
    await write_audit(db, "report.amend", user=actor, entity_type="report", entity_id=new.id,
                      details={"supersedes": old.report_number, "report_number": new.report_number},
                      request=request)
    await db.commit()
    return await report_out(db, scope, new)


async def report_pdf(db: AsyncSession, scope: Scope, report_id: uuid.UUID, variant: str, actor: User,
                     request: Request) -> tuple[bytes, str]:
    report = await db.get(Report, report_id)
    visible_to_patient = (report is not None and scope.is_patient and report.patient_id == scope.patient_id
                          and report.status == "released" and variant == "patient")
    if report is None or report.hospital_id != scope.hospital_id or (scope.is_patient and not visible_to_patient):
        raise not_found("Report")
    if scope.role == "technician" and (report.status != "released" or variant != "patient"):
        raise not_found("Report")
    if variant == "clinician" and scope.role not in AI_RESULT_ROLES:
        raise not_found("Report")
    file_id = report.pdf_file_id if variant == "patient" else report.clinician_pdf_file_id
    if file_id is None:
        raise AppError(409, "NOT_SIGNED", "The PDF is created when the report is signed")
    stored = await db.get(StoredFile, file_id)
    try:
        data = await asyncio.to_thread(storage.decrypt_from_disk, stored)
    except storage.StorageError as exc:
        raise AppError(500, "FILE_UNAVAILABLE", "This report cannot be read from storage") from exc
    await write_audit(db, "report.download", user=actor, entity_type="report", entity_id=report.id,
                      details={"variant": variant, "report_number": report.report_number}, request=request)
    await db.commit()
    return data, f"{report.report_number}-{variant}.pdf"


async def my_reports(db: AsyncSession, scope: Scope) -> list[MyReport]:
    signer = aliased(User)
    rows = (await db.execute(
        select(Report, Lesion.label, Lesion.anatomical_site, signer.full_name)
        .outerjoin(Lesion, Report.lesion_id == Lesion.id).outerjoin(signer, Report.signed_by == signer.id)
        .where(Report.patient_id == scope.patient_id, Report.status == "released")
        .order_by(Report.released_at.desc()))).all()
    return [MyReport(id=r.id, report_number=r.report_number, version=r.version, lesion_label=label,
                     anatomical_site=site, final_category=r.final_category, patient_summary=r.patient_summary,
                     recommendation=r.recommendation, signed_by_name=name, signed_at=r.signed_at,
                     released_at=r.released_at) for r, label, site, name in rows]
