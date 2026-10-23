"""Login, lockout, refresh-token rotation and patient activation."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Request, Response
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (DUMMY_HASH, create_access_token, hash_password, new_refresh_token,
                               normalize_invite_code, sha256_hex, validate_new_password, verify_password)
from app.models import Hospital, Patient, PatientIdentity, PatientInvite, RefreshToken, User
from app.models.base import STAFF_ROLES
from app.schemas.auth import HospitalBrief, MeOut, PatientActivateIn, TokenOut
from app.services.audit import write_audit

REFRESH_COOKIE = "mt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
INVALID_CREDENTIALS = AppError(401, "INVALID_CREDENTIALS", "Incorrect login details")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def build_me(db: AsyncSession, user: User) -> MeOut:
    patient_id = None
    if user.role == "patient":
        patient_id = await db.scalar(select(Patient.id).where(Patient.user_id == user.id))
    hospital = None
    if user.hospital is not None:
        hospital = HospitalBrief(id=user.hospital.id, name=user.hospital.name, code=user.hospital.code)
    return MeOut(id=user.id, role=user.role, full_name=user.full_name, email=user.email, phone=user.phone,
                 hospital=hospital, patient_id=patient_id, must_change_password=user.must_change_password)


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, raw_token, max_age=settings.refresh_token_days * 86400, httponly=True,
        secure=settings.cookie_secure, samesite="strict", path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=settings.cookie_secure,
                           httponly=True, samesite="strict")


async def _issue_tokens(db: AsyncSession, user: User, request: Request, response: Response,
                        family_id: uuid.UUID | None = None) -> TokenOut:
    raw = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=sha256_hex(raw), family_id=family_id or uuid.uuid4(),
        expires_at=_now() + timedelta(days=settings.refresh_token_days),
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500],
    ))
    me = await build_me(db, user)
    access = create_access_token(user_id=user.id, role=user.role, hospital_id=user.hospital_id,
                                 patient_id=me.patient_id)
    set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=settings.access_token_minutes * 60, user=me)


async def _check_password_and_lockout(db: AsyncSession, user: User | None, password: str, request: Request,
                                      portal: str) -> User:
    """Verifies the password, applies the 5-attempt / 15-minute lockout and writes the audit rows."""
    if user is None:
        verify_password(DUMMY_HASH, password)  # equalise timing for unknown accounts
        await write_audit(db, "auth.login_failed", details={"portal": portal, "reason": "unknown_account"},
                          request=request)
        await db.commit()
        raise INVALID_CREDENTIALS

    if user.locked_until and user.locked_until > _now():
        await write_audit(db, "auth.login_failed", user=user, entity_type="user", entity_id=user.id,
                          details={"portal": portal, "reason": "locked"}, request=request)
        await db.commit()
        minutes = max(1, int((user.locked_until - _now()).total_seconds() // 60) + 1)
        raise AppError(423, "ACCOUNT_LOCKED",
                       f"Too many failed attempts. Try again in about {minutes} minute(s).")

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        reason = "bad_password"
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = _now() + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            reason = "locked_now"
        await write_audit(db, "auth.login_failed", user=user, entity_type="user", entity_id=user.id,
                          details={"portal": portal, "reason": reason}, request=request)
        await db.commit()
        raise INVALID_CREDENTIALS

    if not user.is_active:
        await write_audit(db, "auth.login_failed", user=user, entity_type="user", entity_id=user.id,
                          details={"portal": portal, "reason": "inactive"}, request=request)
        await db.commit()
        raise AppError(403, "ACCOUNT_INACTIVE", "This account has been deactivated. Contact your administrator.")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    await write_audit(db, "auth.login", user=user, entity_type="user", entity_id=user.id,
                      details={"portal": portal}, request=request)
    return user


async def _reject_inactive_hospital(db: AsyncSession, user: User, portal: str, request: Request) -> None:
    """Called after a correct password: undo the successful-login bookkeeping and record the refusal."""
    if user.hospital is None or user.hospital.is_active:
        return
    actor = SimpleNamespace(id=user.id, role=user.role, hospital_id=user.hospital_id)  # rollback expires `user`
    await db.rollback()
    await write_audit(db, "auth.login_failed", user=actor, entity_type="user", entity_id=actor.id,
                      details={"portal": portal, "reason": "hospital_inactive"}, request=request)
    await db.commit()
    raise AppError(403, "HOSPITAL_INACTIVE", "This hospital account is inactive")


async def login_hospital(db: AsyncSession, code: str, email: str, password: str, request: Request,
                         response: Response) -> TokenOut:
    user = await db.scalar(select(User).join(Hospital, User.hospital_id == Hospital.id).where(
        Hospital.code == code, User.email == email, User.role.in_(STAFF_ROLES)))
    user = await _check_password_and_lockout(db, user, password, request, "hospital")
    await _reject_inactive_hospital(db, user, "hospital", request)
    out = await _issue_tokens(db, user, request, response)
    await db.commit()
    return out


async def login_patient(db: AsyncSession, identifier: str, password: str, request: Request,
                        response: Response) -> TokenOut:
    ident = identifier.strip()
    phone = "".join(c for c in ident if c.isdigit() or c == "+")
    match = User.email == ident
    if len(phone) >= 7:
        match = or_(match, User.phone == phone)
    user = await db.scalar(select(User).where(User.role == "patient", match))
    user = await _check_password_and_lockout(db, user, password, request, "patient")
    await _reject_inactive_hospital(db, user, "patient", request)
    out = await _issue_tokens(db, user, request, response)
    await db.commit()
    return out


async def login_admin(db: AsyncSession, email: str, password: str, request: Request,
                      response: Response) -> TokenOut:
    user = await db.scalar(select(User).where(User.role == "super_admin", User.email == email))
    user = await _check_password_and_lockout(db, user, password, request, "admin")
    out = await _issue_tokens(db, user, request, response)
    await db.commit()
    return out


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken)
                     .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
                     .values(revoked_at=_now()))


async def refresh(db: AsyncSession, raw: str | None, request: Request, response: Response) -> TokenOut:
    if not raw:
        raise AppError(401, "NO_SESSION", "Not signed in")
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
    if token is None:
        clear_refresh_cookie(response)
        raise AppError(401, "NO_SESSION", "Not signed in")
    if token.revoked_at is not None:
        # Two tabs refreshing at the same moment: the loser presents a token rotated a moment ago while
        # the family is still live. Tell it to retry (the browser already holds the new cookie) and keep
        # the cookie, instead of treating it as theft.
        if (_now() - token.revoked_at).total_seconds() < settings.refresh_reuse_grace_s:
            live = await db.scalar(select(RefreshToken.id).where(
                RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)).limit(1))
            if live is not None:
                raise AppError(401, "REFRESH_RACE", "Session was refreshed in another tab; retry")
        # Otherwise a rotated token was presented again: assume theft and end the whole session family.
        await _revoke_family(db, token.family_id)
        await db.commit()
        clear_refresh_cookie(response)
        raise AppError(401, "TOKEN_REUSED", "Session ended for security reasons. Please sign in again.")
    if token.expires_at <= _now():
        clear_refresh_cookie(response)
        raise AppError(401, "SESSION_EXPIRED", "Session expired. Please sign in again.")

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active or (user.hospital is not None and not user.hospital.is_active):
        await _revoke_family(db, token.family_id)
        await db.commit()
        clear_refresh_cookie(response)
        raise AppError(401, "NO_SESSION", "Not signed in")

    token.revoked_at = _now()
    out = await _issue_tokens(db, user, request, response, family_id=token.family_id)
    await db.commit()
    return out


async def logout(db: AsyncSession, raw: str | None, request: Request, response: Response) -> None:
    if raw:
        token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
        if token is not None:
            await _revoke_family(db, token.family_id)
            user = await db.get(User, token.user_id)
            await write_audit(db, "auth.logout", user=user, entity_type="user", entity_id=token.user_id,
                              request=request)
            await db.commit()
    clear_refresh_cookie(response)


async def change_password(db: AsyncSession, user: User, current: str, new: str, request: Request) -> None:
    if not verify_password(user.password_hash, current):
        raise AppError(400, "WRONG_PASSWORD", "Current password is incorrect")
    if (err := validate_new_password(new)) is not None:
        raise AppError(422, "WEAK_PASSWORD", err)
    if current == new:
        raise AppError(422, "WEAK_PASSWORD", "New password must be different from the current one")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    await write_audit(db, "user.update", user=user, entity_type="user", entity_id=user.id,
                      details={"fields": ["password"], "self": True}, request=request)
    await db.commit()


async def activate_patient(db: AsyncSession, body: PatientActivateIn, request: Request,
                           response: Response) -> TokenOut:
    code_hash = sha256_hex(normalize_invite_code(body.invite_code))
    invite = await db.scalar(select(PatientInvite).where(
        PatientInvite.code_hash == code_hash, PatientInvite.used_at.is_(None), PatientInvite.expires_at > _now()))
    bad = AppError(400, "INVALID_INVITE", "The invite code or date of birth is not valid")
    if invite is None:
        raise bad
    patient = await db.get(Patient, invite.patient_id)
    identity = await db.get(PatientIdentity, invite.patient_id)
    if patient is None or identity is None or identity.date_of_birth != body.date_of_birth:
        raise bad
    if patient.user_id is not None:
        raise AppError(409, "ALREADY_ACTIVATED", "This patient already has an account. Please sign in.")
    if (err := validate_new_password(body.password)) is not None:
        raise AppError(422, "WEAK_PASSWORD", err)

    user = User(hospital_id=patient.hospital_id, role="patient", email=body.email, phone=body.phone,
                password_hash=hash_password(body.password), full_name=identity.full_name,
                must_change_password=False)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "IDENTIFIER_TAKEN", "That email or phone number is already used by another account")
    patient.user_id = user.id
    invite.used_at = _now()
    await write_audit(db, "patient.activate", user=user, entity_type="patient", entity_id=patient.id,
                      request=request)
    await db.refresh(user, attribute_names=["hospital"])
    out = await _issue_tokens(db, user, request, response)
    await db.commit()
    return out
