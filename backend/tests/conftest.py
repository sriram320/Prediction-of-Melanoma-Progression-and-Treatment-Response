"""Test setup: a fresh `<db>_test` database, migrated and seeded once per session.

Run inside compose: `docker compose exec backend pytest -q`
"""
import asyncio
import base64
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
_base = os.environ.get("DATABASE_URL",
                       "postgresql+asyncpg://melanotrack:melanotrack@localhost:5433/melanotrack")
_parts = urlsplit(_base)
TEST_DB = _parts.path.lstrip("/") + "_test"
os.environ.update(
    DATABASE_URL=urlunsplit(_parts._replace(path="/" + TEST_DB)),
    DB_NULL_POOL="true",
    SEED_DEMO="true",
    LOGIN_RATE_LIMIT_PER_MIN="1000",
    REFRESH_REUSE_GRACE_S="0",  # reuse detection is immediate in tests; the grace window has its own test
    SEED_SUPERADMIN_EMAIL="admin@test.example",
    SEED_SUPERADMIN_PASSWORD="InitialPass123!",
    SEED_DEMO_PASSWORD="Demo!2026pass",
    ML_SERVICE_URL="http://127.0.0.1:9",  # unreachable on purpose
)
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("STORAGE_MASTER_KEY", base64.b64encode(b"k" * 32).decode())

ADMIN_EMAIL = "admin@test.example"
ADMIN_INITIAL_PASSWORD = "InitialPass123!"
ADMIN_PASSWORD = "AdminPass456!"
DEMO_PASSWORD = "Demo!2026pass"


def _recreate_database() -> None:
    import psycopg

    admin_url = urlunsplit(_parts._replace(path="/postgres")).replace("+asyncpg", "")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def database():
    _recreate_database()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    from app.scripts import seed
    asyncio.run(seed.run())
    yield


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(database):
    """Logs in the super admin, completing the forced first-login password change once per session."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_INITIAL_PASSWORD})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        r = c.post("/api/v1/auth/change-password", headers=auth(token),
                   json={"current_password": ADMIN_INITIAL_PASSWORD, "new_password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        return token


def staff_login(client, email: str, code: str = "DEMO01", password: str = DEMO_PASSWORD) -> str:
    r = client.post("/api/v1/auth/hospital/login", json={"hospital_code": code, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
