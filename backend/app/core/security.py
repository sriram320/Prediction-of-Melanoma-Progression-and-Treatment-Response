"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""
import hashlib
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

_hasher = PasswordHasher()  # Argon2id with library defaults
JWT_ALG = "HS256"
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# A real hash so that logins for unknown accounts take as long as for known ones.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def validate_new_password(password: str) -> str | None:
    """Returns an error message, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > 128:
        return "Password must be at most 128 characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain at least one letter and one digit"
    return None


def generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length - 1)) + secrets.choice("!@#$%&*")
        if validate_new_password(pw) is None and any(c.isupper() for c in pw):
            return pw


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def create_access_token(*, user_id: uuid.UUID, role: str, hospital_id: uuid.UUID | None,
                        patient_id: uuid.UUID | None) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "role": role,
        "hid": str(hospital_id) if hospital_id else None,
        "pid": str(patient_id) if patient_id else None,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError if the token is invalid or expired."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALG], options={"require": ["exp", "sub"]})


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def generate_invite_code() -> str:
    raw = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalize_invite_code(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())
