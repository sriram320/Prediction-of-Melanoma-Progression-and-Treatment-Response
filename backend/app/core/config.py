"""Application settings, read from environment variables (and `.env` for local runs)."""
import base64
import binascii

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDERS = {"", "change-me", "changeme"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://melanotrack:melanotrack@localhost:5433/melanotrack"
    db_null_pool: bool = False  # tests run the app and the seed in different event loops

    # Auth
    jwt_secret: str = "change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    refresh_reuse_grace_s: int = 10  # concurrent refreshes from two tabs are not treated as theft
    cookie_secure: bool = False
    login_rate_limit_per_min: int = 10
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    invite_valid_days: int = 7

    # Files
    storage_root: str = "/data/storage"
    storage_master_key: str = "change-me"
    max_upload_mb: int = 50
    max_files_per_upload: int = 10

    # Seed
    seed_superadmin_email: str = "admin@melanotrack.example"
    seed_superadmin_password: str = "ChangeMe!2026"
    seed_demo: bool = False
    seed_demo_password: str = "Demo!2026pass"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    # AI model service and inference worker
    ml_service_url: str = "http://ml-service:8100"
    inference_timeout_s: int = 60
    embedded_worker: bool = True  # run the job worker inside the API process (local dev); compose uses its own
    worker_poll_s: float = 1.0
    job_stale_after_s: int = 300  # a 'running' job older than this is assumed orphaned and re-queued
    job_max_attempts: int = 3
    segmentation_confidence_threshold: float = 0.6

    # Reports
    display_timezone: str = "Asia/Kolkata"  # timestamps printed on reports
    report_font_path: str | None = None  # a Unicode .ttf; found automatically on Windows (Arial) and Docker (DejaVu)
    report_font_bold_path: str | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong(cls, v: str) -> str:
        if v.strip().lower() in _PLACEHOLDERS or len(v) < 32:
            raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters")
        return v

    @field_validator("storage_master_key")
    @classmethod
    def _master_key_is_32_bytes(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) != 32:
            raise ValueError("STORAGE_MASTER_KEY must be 32 random bytes, base64-encoded")
        return v

    @property
    def master_key_bytes(self) -> bytes:
        return base64.b64decode(self.storage_master_key)


settings = Settings()
