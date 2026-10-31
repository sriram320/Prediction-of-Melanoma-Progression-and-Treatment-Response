"""Encrypted file records, de-duplication, and read access.

Read access is derived from what a file is attached to, never from the file alone:
- a scan image: staff of the hospital, or the patient it belongs to (original DICOMs: staff only);
- a document: staff of the hospital, or the patient when the document is shared with them;
- an AI output (segmentation mask, difference map, saliency map): hospital admins and doctors only.
Anything else (future report PDFs) is unreadable until its phase adds a rule (fail closed).
"""
import asyncio
import hashlib
import re
import uuid
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import settings
from app.core.deps import Scope
from app.core.errors import AppError, not_found
from app.models import Document, Explanation, Image, Lesion, StoredFile, User, Visit
from app.services import imaging
from app.services.audit import write_audit

AI_RESULT_ROLES = ("hospital_admin", "doctor")


def clean_filename(name: str | None) -> str:
    base = PurePosixPath((name or "upload").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\"]", "", base).strip() or "upload"
    return base[-255:]


async def read_upload(upload: UploadFile) -> bytes:
    """Reads one uploaded file, refusing anything over MAX_UPLOAD_MB."""
    limit = settings.max_upload_mb * 1024 * 1024
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise imaging.UploadRejected(f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise imaging.UploadRejected("File is empty")
    return data


async def store(db: AsyncSession, *, hospital_id: uuid.UUID, data: bytes, mime: str, filename: str,
                uploaded_by: uuid.UUID | None) -> tuple[StoredFile, bool]:
    """Encrypts and records a file. Returns (file, duplicate); an identical file in the hospital is reused."""
    digest = hashlib.sha256(data).hexdigest()
    existing = await db.scalar(select(StoredFile).where(StoredFile.hospital_id == hospital_id,
                                                        StoredFile.sha256 == digest))
    if existing is not None:
        return existing, True
    file_id = uuid.uuid4()
    blob = await asyncio.to_thread(storage.encrypt_to_disk, file_id, hospital_id, data)
    stored = StoredFile(id=file_id, hospital_id=hospital_id, sha256=digest, size_bytes=len(data), mime_type=mime,
                        original_filename=filename, storage_path=blob.storage_path, enc_algo=storage.ALGO,
                        wrapped_dek=blob.wrapped_dek, nonce=blob.nonce, key_version=storage.KEY_VERSION,
                        uploaded_by=uploaded_by)
    db.add(stored)
    await db.flush()
    return stored, False


async def readable_file(db: AsyncSession, scope: Scope, file_id: uuid.UUID) -> StoredFile:
    stored = await db.get(StoredFile, file_id)
    if stored is None or stored.hospital_id != scope.hospital_id:
        raise not_found("File")

    image_match = Image.file_id == file_id
    if not scope.is_patient:
        image_match = or_(image_match, Image.source_file_id == file_id)
    owners = set((await db.scalars(
        select(Lesion.patient_id).select_from(Image).join(Visit, Image.visit_id == Visit.id)
        .join(Lesion, Visit.lesion_id == Lesion.id).where(image_match))).all())
    if owners and (not scope.is_patient or scope.patient_id in owners):
        return stored

    for patient_id, visible in (await db.execute(
            select(Document.patient_id, Document.visible_to_patient).where(Document.file_id == file_id))).all():
        if not scope.is_patient or (patient_id == scope.patient_id and visible):
            return stored

    if scope.role in AI_RESULT_ROLES:
        ai_output = await db.scalar(select(Image.id).where(Image.mask_file_id == file_id).limit(1))
        if ai_output is None:
            ai_output = await db.scalar(select(Explanation.id).where(or_(
                Explanation.difference_map_file_id == file_id, Explanation.saliency_file_id == file_id)).limit(1))
        if ai_output is not None:
            return stored
    raise not_found("File")


def _disposition(kind: str, filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "file"
    return f'{kind}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


FILE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


def _decrypt(stored: StoredFile) -> bytes:
    try:
        return storage.decrypt_from_disk(stored)
    except storage.StorageError as exc:
        raise AppError(500, "FILE_UNAVAILABLE", "This file cannot be read from storage") from exc


async def read_content(db: AsyncSession, scope: Scope, file_id: uuid.UUID, actor: User, request: Request,
                       download: bool) -> tuple[bytes, str, dict]:
    stored = await readable_file(db, scope, file_id)
    data = await asyncio.to_thread(_decrypt, stored)
    await write_audit(db, "file.read", user=actor, entity_type="file", entity_id=stored.id,
                      details={"variant": "original", "download": download}, request=request)
    await db.commit()
    name = stored.original_filename or f"{stored.id}"
    headers = {**FILE_HEADERS, "Content-Disposition": _disposition("attachment" if download else "inline", name)}
    return data, stored.mime_type, headers


async def read_thumbnail(db: AsyncSession, scope: Scope, file_id: uuid.UUID, size: int, actor: User,
                         request: Request) -> tuple[bytes, dict]:
    if size not in imaging.THUMBNAIL_SIZES:
        raise AppError(422, "VALIDATION_ERROR", f"size must be one of {list(imaging.THUMBNAIL_SIZES)}")
    stored = await readable_file(db, scope, file_id)
    if stored.mime_type not in (imaging.JPEG, imaging.PNG):
        raise AppError(415, "NO_THUMBNAIL", "No preview is available for this file type")

    def build() -> bytes:
        cached = storage.read_cached_thumbnail(stored, size)
        if cached is not None:
            return cached
        thumb = imaging.make_thumbnail(_decrypt(stored), size)
        storage.write_cached_thumbnail(stored, size, thumb)
        return thumb

    data = await asyncio.to_thread(build)
    await write_audit(db, "file.read", user=actor, entity_type="file", entity_id=stored.id,
                      details={"variant": f"thumbnail_{size}"}, request=request)
    await db.commit()
    return data, FILE_HEADERS
