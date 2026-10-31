"""Patient documents (lab reports, histopathology, prescriptions...). Patients see only shared documents."""
import asyncio
import uuid
from datetime import date, timedelta

from fastapi import Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import Document, Lesion, StoredFile, User
from app.schemas.records import DocumentOut
from app.services import files as files_svc
from app.services import imaging
from app.services.audit import write_audit
from app.services.patients import patient_in_scope

SHARE_ROLES = ("hospital_admin", "doctor")


def _documents_query():
    return (select(Document, StoredFile.mime_type, StoredFile.size_bytes, StoredFile.original_filename,
                   User.full_name.label("uploaded_by_name"))
            .join(StoredFile, Document.file_id == StoredFile.id)
            .outerjoin(User, Document.uploaded_by == User.id))


def _out(row) -> DocumentOut:
    doc = row.Document
    return DocumentOut(id=doc.id, patient_id=doc.patient_id, lesion_id=doc.lesion_id, file_id=doc.file_id,
                       category=doc.category, title=doc.title, document_date=doc.document_date,
                       visible_to_patient=doc.visible_to_patient, mime_type=row.mime_type, size_bytes=row.size_bytes,
                       original_filename=row.original_filename, uploaded_by_name=row.uploaded_by_name,
                       created_at=doc.created_at)


async def list_documents(db: AsyncSession, scope: Scope, patient_id: uuid.UUID,
                         category: str | None = None) -> list[DocumentOut]:
    await patient_in_scope(db, scope, patient_id)
    stmt = _documents_query().where(Document.patient_id == patient_id)
    if category:
        stmt = stmt.where(Document.category == category)
    if scope.is_patient:
        stmt = stmt.where(Document.visible_to_patient.is_(True))
    rows = (await db.execute(stmt.order_by(Document.document_date.desc().nulls_last(),
                                           Document.created_at.desc()))).all()
    return [_out(r) for r in rows]


async def upload_document(db: AsyncSession, scope: Scope, patient_id: uuid.UUID, upload: UploadFile, *,
                          category: str, title: str, document_date: date | None, lesion_id: uuid.UUID | None,
                          visible_to_patient: bool, actor: User, request: Request) -> DocumentOut:
    patient = await patient_in_scope(db, scope, patient_id)
    title = title.strip()
    if not 1 <= len(title) <= 200:
        raise AppError(422, "VALIDATION_ERROR", "title: enter a title of up to 200 characters")
    if document_date is not None and document_date > date.today() + timedelta(days=1):
        raise AppError(422, "VALIDATION_ERROR", "document_date: cannot be in the future")
    if visible_to_patient and actor.role not in SHARE_ROLES:
        raise AppError(403, "FORBIDDEN", "Only doctors and hospital admins can share documents with the patient")
    if lesion_id is not None:
        lesion = await db.get(Lesion, lesion_id)
        if lesion is None or lesion.patient_id != patient.id:
            raise AppError(422, "VALIDATION_ERROR", "lesion_id: that lesion does not belong to this patient")

    name = files_svc.clean_filename(upload.filename)
    try:
        raw = await files_svc.read_upload(upload)
        mime = imaging.sniff_mime(raw)
        if mime not in imaging.DOCUMENT_TYPES:
            raise imaging.UploadRejected("Not a supported document type (use PDF, JPEG, PNG or TIFF)")
        data, mime = await asyncio.to_thread(imaging.prepare_document, raw, mime)
    except imaging.UploadRejected as exc:
        raise AppError(422, "INVALID_FILE", str(exc))

    stored, duplicate = await files_svc.store(db, hospital_id=patient.hospital_id, data=data, mime=mime,
                                              filename=name, uploaded_by=actor.id)
    if duplicate:
        existing = await db.scalar(select(Document.title).where(Document.file_id == stored.id,
                                                                Document.patient_id == patient.id).limit(1))
        if existing is not None:
            raise AppError(409, "DUPLICATE_DOCUMENT", f'This file is already in the record as "{existing}"')
    doc = Document(patient_id=patient.id, hospital_id=patient.hospital_id, lesion_id=lesion_id, file_id=stored.id,
                   category=category, title=title, document_date=document_date,
                   visible_to_patient=visible_to_patient, uploaded_by=actor.id)
    db.add(doc)
    await db.flush()
    await write_audit(db, "file.upload", user=actor, entity_type="document", entity_id=doc.id,
                      details={"patient_id": str(patient.id), "file_id": str(stored.id), "category": category,
                               "visible_to_patient": visible_to_patient, "mime": mime, "bytes": len(data)},
                      request=request)
    await db.commit()
    row = (await db.execute(_documents_query().where(Document.id == doc.id))).one()
    return _out(row)


async def set_visibility(db: AsyncSession, scope: Scope, document_id: uuid.UUID, visible: bool, actor: User,
                         request: Request) -> DocumentOut:
    doc = await db.get(Document, document_id)
    if doc is None or doc.hospital_id != scope.hospital_id:
        raise not_found("Document")
    if doc.visible_to_patient != visible:
        doc.visible_to_patient = visible
        await write_audit(db, "document.visibility", user=actor, entity_type="document", entity_id=doc.id,
                          details={"visible_to_patient": visible}, request=request)
        await db.commit()
    row = (await db.execute(_documents_query().where(Document.id == doc.id))).one()
    return _out(row)
