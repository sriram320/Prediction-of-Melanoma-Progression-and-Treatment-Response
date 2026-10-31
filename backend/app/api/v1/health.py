import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models import ModelVersion

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Public. Also tells the UI whether the active model is a mock (drives the watermark)."""
    db_status = "ok"
    model = None
    try:
        await db.execute(text("SELECT 1"))
        mv = await db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
        if mv is not None:
            model = {"name": mv.name, "version": mv.version, "is_mock": mv.is_mock}
    except Exception:
        db_status = "error"

    ml_status, ml_model = "unavailable", None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.ml_service_url}/health")
            if r.status_code == 200:
                ml_status = "ok"
                body = r.json()
                ml_model = {"name": body.get("model_name"), "version": body.get("model_version"),
                            "is_mock": body.get("is_mock")}
    except (httpx.HTTPError, ValueError):
        pass

    # Fail safe: if we cannot tell which model is active, treat it as a mock (watermark stays on).
    if model is None:
        model = {"name": None, "version": None, "is_mock": True}
    # A mismatch means every analysis is refused as `model_error` until the registry and ml-service agree.
    model_match = ml_model is not None and all(ml_model[k] == model[k] for k in ("name", "version", "is_mock"))
    return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status, "ml_service": ml_status,
            "model": model, "ml_model": ml_model, "model_match": model_match}
