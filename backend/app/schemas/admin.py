import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel, blank_to_none, normalize_phone

HOSPITAL_CODE_RE = re.compile(r"^[A-Z0-9]{3,16}$")
StaffRole = Literal["hospital_admin", "doctor", "technician"]


class HospitalCreate(BaseModel):
    code: str
    name: str = Field(min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    _blank = field_validator("address", "contact_email", mode="before")(blank_to_none)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not HOSPITAL_CODE_RE.match(v):
            raise ValueError("Hospital code must be 3-16 letters or digits")
        return v

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class HospitalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    is_active: bool | None = None

    _blank = field_validator("address", "contact_email", mode="before")(blank_to_none)

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class HospitalOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    address: str | None
    contact_email: str | None
    contact_phone: str | None
    is_active: bool
    created_at: datetime
    staff_count: int = 0
    patient_count: int = 0


class StaffCreate(BaseModel):
    role: StaffRole
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = None
    registration_no: str | None = Field(default=None, max_length=50)

    _blank = field_validator("registration_no", mode="before")(blank_to_none)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class HospitalAdminCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class StaffUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = None
    registration_no: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    reset_password: bool = False

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


class StaffOut(ORMModel):
    id: uuid.UUID
    role: str
    full_name: str
    email: str | None
    phone: str | None
    registration_no: str | None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    created_at: datetime


class StaffWithPassword(BaseModel):
    user: StaffOut
    temp_password: str | None = Field(
        default=None, description="Shown once. The user must change it at first login.")


class HospitalDetailOut(HospitalOut):
    admins: list[StaffOut] = []


class HospitalStats(BaseModel):
    patients: int
    lesions: int
    visits: int
    pending_reviews: int
    open_referrals: int
    reports_released: int
    staff: int
