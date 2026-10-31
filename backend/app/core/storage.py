"""Encrypted file storage on local disk.

Each file gets a random 256-bit data key (DEK) and is encrypted with AES-256-GCM; the DEK is wrapped with
STORAGE_MASTER_KEY (RFC 3394 key wrap) and kept in `stored_files.wrapped_dek`. The file id is bound into the
GCM associated data, so swapping two ciphertexts on disk is detected on decrypt.

Layout: {STORAGE_ROOT}/{hospital_id}/{yyyy}/{mm}/{file_id}.bin, thumbnails under {STORAGE_ROOT}/_thumbs/.
Nothing here is ever served statically.
"""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

from app.core.config import settings

ALGO = "AES-256-GCM"
KEY_VERSION = 1
NONCE_BYTES = 12


class StorageError(Exception):
    """The file is missing, was tampered with, or the master key does not match."""


@dataclass(frozen=True)
class EncryptedBlob:
    storage_path: str
    wrapped_dek: bytes
    nonce: bytes


def _root() -> Path:
    return Path(settings.storage_root).resolve()


def _resolve(rel: str) -> Path:
    path = (_root() / rel).resolve()
    if _root() not in path.parents:
        raise StorageError("Storage path escapes the storage root")
    return path


def _aad(file_id: uuid.UUID, purpose: str) -> bytes:
    return f"melanotrack:{purpose}:{file_id}".encode()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _unwrap(wrapped_dek: bytes) -> bytes:
    try:
        return aes_key_unwrap(settings.master_key_bytes, wrapped_dek)
    except InvalidUnwrap as exc:
        raise StorageError("The file key cannot be unwrapped (wrong STORAGE_MASTER_KEY?)") from exc


def encrypt_to_disk(file_id: uuid.UUID, hospital_id: uuid.UUID, data: bytes) -> EncryptedBlob:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, data, _aad(file_id, "file"))
    now = datetime.now(timezone.utc)
    rel = f"{hospital_id}/{now:%Y}/{now:%m}/{file_id}.bin"
    _write_atomic(_resolve(rel), ciphertext)
    return EncryptedBlob(storage_path=rel, wrapped_dek=aes_key_wrap(settings.master_key_bytes, dek), nonce=nonce)


def decrypt_from_disk(stored) -> bytes:
    """`stored` is a StoredFile row (id, storage_path, wrapped_dek, nonce)."""
    try:
        ciphertext = _resolve(stored.storage_path).read_bytes()
    except FileNotFoundError as exc:
        raise StorageError("The encrypted file is missing from storage") from exc
    try:
        return AESGCM(_unwrap(stored.wrapped_dek)).decrypt(stored.nonce, ciphertext, _aad(stored.id, "file"))
    except InvalidTag as exc:
        raise StorageError("The encrypted file failed its integrity check") from exc


def _thumb_path(stored, size: int) -> Path:
    return _resolve(f"_thumbs/{stored.hospital_id}/{stored.id}_{size}.bin")


def read_cached_thumbnail(stored, size: int) -> bytes | None:
    """Thumbnails are encrypted with the file's own DEK; the cache file is nonce || ciphertext."""
    path = _thumb_path(stored, size)
    if not path.exists():
        return None
    blob = path.read_bytes()
    try:
        return AESGCM(_unwrap(stored.wrapped_dek)).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:],
                                                           _aad(stored.id, f"thumb{size}"))
    except InvalidTag:
        path.unlink(missing_ok=True)  # a corrupt cache entry is simply regenerated
        return None


def write_cached_thumbnail(stored, size: int, data: bytes) -> None:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_unwrap(stored.wrapped_dek)).encrypt(nonce, data, _aad(stored.id, f"thumb{size}"))
    _write_atomic(_thumb_path(stored, size), nonce + ciphertext)
