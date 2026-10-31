"""Test setup: a fresh `<db>_test` database (migrated and seeded once per session) and a temporary storage folder.

Run: `cd backend; .venv\\Scripts\\python -m pytest -q` (or `docker compose exec backend pytest -q`).
The server and credentials come from DATABASE_URL, else from the repo's .env; only the database name changes.
"""
import asyncio
import base64
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _dotenv_value(key: str) -> str | None:
    env_file = BACKEND_DIR.parent / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name == key:
            return value.strip().strip('"').strip("'")
    return None


_base = (os.environ.get("DATABASE_URL") or _dotenv_value("DATABASE_URL")
         or "postgresql+asyncpg://melanotrack:melanotrack@localhost:5433/melanotrack")
_parts = urlsplit(_base)
TEST_DB = _parts.path.lstrip("/") + "_test"
STORAGE_DIR = tempfile.mkdtemp(prefix="melanotrack-test-storage-")
# Environment variables win over .env in pydantic-settings, so the app below only ever sees the test database
# and the temporary storage folder.
os.environ.update(
    DATABASE_URL=urlunsplit(_parts._replace(path="/" + TEST_DB)),
    DB_NULL_POOL="true",
    STORAGE_ROOT=STORAGE_DIR,
    SEED_DEMO="true",
    LOGIN_RATE_LIMIT_PER_MIN="1000",
    REFRESH_REUSE_GRACE_S="0",  # reuse detection is immediate in tests; the grace window has its own test
    SEED_SUPERADMIN_EMAIL="admin@test.example",
    SEED_SUPERADMIN_PASSWORD="InitialPass123!",
    SEED_DEMO_PASSWORD="Demo!2026pass",
    ML_SERVICE_URL="http://127.0.0.1:9",  # unreachable on purpose; analysis tests mount the ml-service in-process
    EMBEDDED_WORKER="false",  # tests run jobs explicitly with run_worker()
    JWT_SECRET="test-secret-" + "x" * 40,
    STORAGE_MASTER_KEY=base64.b64encode(b"k" * 32).decode(),
)

ADMIN_EMAIL = "admin@test.example"
ADMIN_INITIAL_PASSWORD = "InitialPass123!"
ADMIN_PASSWORD = "AdminPass456!"
DEMO_PASSWORD = "Demo!2026pass"
API = "/api/v1"


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
    shutil.rmtree(STORAGE_DIR, ignore_errors=True)


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
        r = c.post(f"{API}/auth/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_INITIAL_PASSWORD})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        r = c.post(f"{API}/auth/change-password", headers=auth(token),
                   json={"current_password": ADMIN_INITIAL_PASSWORD, "new_password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        return token


def staff_login(client, email: str, code: str = "DEMO01", password: str = DEMO_PASSWORD) -> str:
    r = client.post(f"{API}/auth/hospital/login", json={"hospital_code": code, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def patient_login(client, identifier: str = "patient@demo.example", password: str = DEMO_PASSWORD) -> str:
    r = client.post(f"{API}/auth/patient/login", json={"identifier": identifier, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def second_hospital(client, admin_token) -> tuple[str, str]:
    """Creates hospital SECOND (once) with an admin; returns (hospital_id, admin access token)."""
    r = client.get(f"{API}/admin/hospitals?q=SECOND", headers=auth(admin_token))
    if r.json()["total"] == 0:
        r = client.post(f"{API}/admin/hospitals", headers=auth(admin_token),
                        json={"code": "second", "name": "Second Hospital", "contact_phone": "+91 80 1234 5678"})
        assert r.status_code == 201, r.text
        hid = r.json()["id"]
        r = client.post(f"{API}/admin/hospitals/{hid}/admins", headers=auth(admin_token),
                        json={"full_name": "Second Admin", "email": "admin2@second.example"})
        assert r.status_code == 201, r.text
        temp = r.json()["temp_password"]
        login = client.post(f"{API}/auth/hospital/login",
                            json={"hospital_code": "SECOND", "email": "admin2@second.example", "password": temp})
        tok = login.json()["access_token"]
        client.post(f"{API}/auth/change-password", headers=auth(tok),
                    json={"current_password": temp, "new_password": "SecondAdmin123"})
    else:
        hid = r.json()["items"][0]["id"]
    tok = staff_login(client, "admin2@second.example", code="SECOND", password="SecondAdmin123")
    return hid, tok


ML_APP_DIR = BACKEND_DIR.parent / "ml_service" / "app"


def _load_ml_service():
    """Imports ml_service/app as package `mlsvc` (both services name their package `app`)."""
    import importlib
    import importlib.util
    import sys

    if "mlsvc.main" not in sys.modules:
        spec = importlib.util.spec_from_file_location("mlsvc", ML_APP_DIR / "__init__.py",
                                                      submodule_search_locations=[str(ML_APP_DIR)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules["mlsvc"] = pkg
        spec.loader.exec_module(pkg)
    return importlib.import_module("mlsvc.main"), importlib.import_module("mlsvc.adapters")


@pytest.fixture
def ml(monkeypatch):
    """Routes the backend's ml-service calls to the real ml-service app, in process."""
    from types import SimpleNamespace

    import httpx
    from app.services import ml_client

    main, adapters = _load_ml_service()
    monkeypatch.delenv("MOCK_FORCE_ERROR", raising=False)
    monkeypatch.setattr(ml_client, "transport", httpx.ASGITransport(app=main.app))
    return SimpleNamespace(client=ml_client, adapter=adapters.get_adapter())
