import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.common import blank_to_none, normalize_phone


# Login bodies take plain strings: a malformed email at sign-in is just "incorrect login details",
# never a validation error. Account creation still uses EmailStr.
class HospitalLoginIn(BaseModel):
    hospital_code: str = Field(min_length=1, max_length=16)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("hospital_code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("email")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class PatientLoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=200, description="Email or phone number")
    password: str = Field(min_length=1, max_length=128)


class AdminLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class PatientActivateIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=40)
    date_of_birth: date
    email: EmailStr | None = None
    phone: str | None = None
    password: str = Field(min_length=1, max_length=128)

    _blank = field_validator("email", mode="before")(blank_to_none)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)

    @model_validator(mode="after")
    def _needs_identifier(self):
        if not self.email and not self.phone:
            raise ValueError("Provide an email address or a phone number to log in with")
        return self


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class HospitalBrief(BaseModel):
    id: uuid.UUID
    name: str
    code: str


class MeOut(BaseModel):
    id: uuid.UUID
    role: str
    full_name: str
    email: str | None
    phone: str | None
    hospital: HospitalBrief | None
    patient_id: uuid.UUID | None
    must_change_password: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: MeOut
