"""MelanoTrack ml-service. Internal only (no published port); called by the backend worker.

P0 skeleton: /health only. P3 adds POST /infer with the ModelAdapter registry (mock first),
following .agents/skills/melanotrack-platform/references/model_integration.md.
"""
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

ADAPTER = os.environ.get("MODEL_ADAPTER", "mock")
MODEL_DIR = os.environ.get("MODEL_DIR", "/models/mock/0.1.0")

app = FastAPI(title="MelanoTrack ml-service", version="0.1.0", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "adapter": ADAPTER,
        "model_name": "mock" if ADAPTER == "mock" else ADAPTER,
        "model_version": os.path.basename(MODEL_DIR.rstrip("/")) or None,
        "is_mock": ADAPTER == "mock",
        "device": "cpu",
    }


@app.post("/infer")
def infer() -> JSONResponse:
    # Not implemented until P3. The backend treats any non-200 as model_error => referral (NFR-03).
    return JSONResponse({"detail": "Inference is not implemented yet (phase P3)", "code": "NOT_IMPLEMENTED"},
                        status_code=501)
