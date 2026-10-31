"""Patient portal: the signed-in patient's own record only."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import Scope, get_scope, require_roles
from app.schemas.records import MyDocument, MyLesion, MyOverview
from app.schemas.reports import MyReport
from app.services import me as me_svc
from app.services import reports as reports_svc

router = APIRouter(prefix="/me", tags=["patient portal"], dependencies=[Depends(require_roles("patient"))])


@router.get("/overview", response_model=MyOverview)
async def overview(scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await me_svc.overview(db, scope)


@router.get("/lesions", response_model=list[MyLesion])
async def lesions(scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await me_svc.my_lesions(db, scope)


@router.get("/documents", response_model=list[MyDocument])
async def documents(scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    return await me_svc.my_documents(db, scope)


@router.get("/reports", response_model=list[MyReport])
async def reports(scope: Scope = Depends(get_scope), db: AsyncSession = Depends(get_db)):
    """Released reports only; download with GET /reports/{id}/pdf (patient copy)."""
    return await reports_svc.my_reports(db, scope)
