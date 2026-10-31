"""Decrypted file streaming (permission-checked and audited) and document sharing."""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.models import User
from app.schemas.records import DocumentOut, DocumentVisibility
from app.services import documents as documents_svc
from app.services import files as files_svc

router = APIRouter(tags=["files & documents"])
Readers = Depends(require_roles("hospital_admin", "doctor", "technician", "patient"))


@router.get("/files/{file_id}/content", response_class=Response)
async def file_content(file_id: uuid.UUID, request: Request, download: bool = False, actor: User = Readers,
                       scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    data, mime, headers = await files_svc.read_content(db, scope, file_id, actor, request, download)
    return Response(content=data, media_type=mime, headers=headers)


@router.get("/files/{file_id}/thumbnail", response_class=Response)
async def file_thumbnail(file_id: uuid.UUID, request: Request, size: int = Query(256), actor: User = Readers,
                         scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    data, headers = await files_svc.read_thumbnail(db, scope, file_id, size, actor, request)
    return Response(content=data, media_type="image/jpeg", headers=headers)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def set_document_visibility(document_id: uuid.UUID, body: DocumentVisibility, request: Request,
                                  actor: User = Depends(require_roles(*documents_svc.SHARE_ROLES)),
                                  scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await documents_svc.set_visibility(db, scope, document_id, body.visible_to_patient, actor, request)
