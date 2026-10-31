import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop, task = asyncio.Event(), None
    if settings.embedded_worker:
        from app.workers.inference_worker import run_forever

        task = asyncio.create_task(run_forever(stop))
    yield
    if task is not None:
        stop.set()
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=settings.inference_timeout_s + 5)


app = FastAPI(
    title="MelanoTrack API",
    version="0.1.0",
    description="Longitudinal melanoma progression platform - decision support, not a diagnosis.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_error_handlers(app)
app.include_router(api_router)
