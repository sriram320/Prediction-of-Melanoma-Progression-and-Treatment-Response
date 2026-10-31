"""Patient portal data. Always the caller's own record; never AI predictions (invariant 4)."""
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Scope
from app.models import Document, Hospital, Image, Lesion, Patient, StoredFile, Visit
from app.schemas.records import MyDocument, MyImage, MyLesion, MyOverview, MyVisit


async def overview(db: AsyncSession, scope: Scope) -> MyOverview:
    patient = await db.get(Patient, scope.patient_id)
    hospital = await db.get(Hospital, patient.hospital_id)
    visible_visits = (select(Visit).join(Lesion, Visit.lesion_id == Lesion.id)
                      .where(Lesion.patient_id == patient.id, Visit.excluded.is_(False)).subquery())
    return MyOverview(
        full_name=patient.identity.full_name, hospital_name=hospital.name, mrn=patient.mrn,
        lesion_count=await db.scalar(select(func.count()).select_from(Lesion).where(Lesion.patient_id == patient.id)),
        visit_count=await db.scalar(select(func.count()).select_from(visible_visits)),
        document_count=await db.scalar(select(func.count()).select_from(Document).where(
            Document.patient_id == patient.id, Document.visible_to_patient.is_(True))),
        last_visit_date=await db.scalar(select(func.max(visible_visits.c.visit_date))),
    )


async def my_lesions(db: AsyncSession, scope: Scope) -> list[MyLesion]:
    lesions = (await db.scalars(select(Lesion).where(Lesion.patient_id == scope.patient_id)
                                .order_by(Lesion.created_at))).all()
    if not lesions:
        return []
    visits = (await db.scalars(select(Visit).where(Visit.lesion_id.in_([l.id for l in lesions]),
                                                   Visit.excluded.is_(False))
                               .order_by(Visit.visit_date))).all()
    images: dict = defaultdict(list)
    if visits:
        for img in (await db.scalars(select(Image).where(Image.visit_id.in_([v.id for v in visits]))
                                     .order_by(Image.created_at))).all():
            images[img.visit_id].append(MyImage(id=img.id, file_id=img.file_id, modality=img.modality,
                                                width=img.width, height=img.height))
    by_lesion: dict = defaultdict(list)
    for v in visits:
        by_lesion[v.lesion_id].append(MyVisit(id=v.id, visit_date=v.visit_date, images=images[v.id]))
    return [MyLesion(id=l.id, label=l.label, anatomical_site=l.anatomical_site, status=l.status,
                     visits=by_lesion[l.id]) for l in lesions]


async def my_documents(db: AsyncSession, scope: Scope) -> list[MyDocument]:
    rows = (await db.execute(
        select(Document, StoredFile.mime_type, StoredFile.size_bytes).join(StoredFile, Document.file_id == StoredFile.id)
        .where(Document.patient_id == scope.patient_id, Document.visible_to_patient.is_(True))
        .order_by(Document.document_date.desc().nulls_last(), Document.created_at.desc()))).all()
    return [MyDocument(id=r.Document.id, title=r.Document.title, category=r.Document.category,
                       document_date=r.Document.document_date, file_id=r.Document.file_id, mime_type=r.mime_type,
                       size_bytes=r.size_bytes, created_at=r.Document.created_at) for r in rows]
