from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import client_ip, get_current_user_allow_password_change
from app.core.ratelimit import login_limiter
from app.models import User
from app.schemas.auth import (AdminLoginIn, ChangePasswordIn, HospitalLoginIn, MeOut, PatientActivateIn,
                              PatientLoginIn, TokenOut)
from app.services import auth as svc
from app.services.auth import REFRESH_COOKIE

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request) -> None:
    login_limiter.hit(client_ip(request) or "unknown")


@router.post("/hospital/login", response_model=TokenOut)
async def hospital_login(body: HospitalLoginIn, request: Request, response: Response,
                         db: AsyncSession = Depends(get_db)):
    _limit(request)
    return await svc.login_hospital(db, body.hospital_code, body.email, body.password, request, response)


@router.post("/patient/login", response_model=TokenOut)
async def patient_login(body: PatientLoginIn, request: Request, response: Response,
                        db: AsyncSession = Depends(get_db)):
    _limit(request)
    return await svc.login_patient(db, body.identifier, body.password, request, response)


@router.post("/admin/login", response_model=TokenOut)
async def admin_login(body: AdminLoginIn, request: Request, response: Response,
                      db: AsyncSession = Depends(get_db)):
    _limit(request)
    return await svc.login_admin(db, body.email, body.password, request, response)


@router.post("/patient/activate", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def patient_activate(body: PatientActivateIn, request: Request, response: Response,
                           db: AsyncSession = Depends(get_db)):
    _limit(request)  # invite codes and dates of birth must not be brute-forced either
    return await svc.activate_patient(db, body, request, response)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db),
                  mt_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE)):
    return await svc.refresh(db, mt_refresh, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db),
                 mt_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE)):
    await svc.logout(db, mt_refresh, request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user_allow_password_change), db: AsyncSession = Depends(get_db)):
    return await svc.build_me(db, user)


@router.post("/change-password", response_model=MeOut)
async def change_password(body: ChangePasswordIn, request: Request,
                          user: User = Depends(get_current_user_allow_password_change),
                          db: AsyncSession = Depends(get_db)):
    await svc.change_password(db, user, body.current_password, body.new_password, request)
    return await svc.build_me(db, user)
