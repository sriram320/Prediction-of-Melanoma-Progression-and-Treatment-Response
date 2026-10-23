import re
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def normalize_phone(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not PHONE_RE.match(v):
        raise ValueError("Enter a valid phone number (digits, optional leading +)")
    return re.sub(r"[ \-]", "", v)


def blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v.strip() if isinstance(v, str) else v
