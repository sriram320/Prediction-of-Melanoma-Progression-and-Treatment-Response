import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CHAR, ForeignKey, LargeBinary, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class StoredFile(Base):
    """An encrypted file on the storage volume. `storage_path` and `wrapped_dek` never leave the backend."""
    __tablename__ = "stored_files"

    id: Mapped[uuid.UUID] = uuid_pk()
    hospital_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    sha256: Mapped[str] = mapped_column(CHAR(64))  # of the plaintext
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    enc_algo: Mapped[str] = mapped_column(String(20), default="AES-256-GCM")
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(SmallInteger, default=1)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
