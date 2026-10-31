"""Inference worker: claims queued jobs from PostgreSQL (FOR UPDATE SKIP LOCKED) and runs them.

Standalone: `python -m app.workers.inference_worker` (the compose `worker` service).
Embedded: started inside the API process when EMBEDDED_WORKER=true (default for local development).
Several workers can run at once; SKIP LOCKED gives each job to exactly one of them.
"""
import asyncio
import logging
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.services import inference

log = logging.getLogger("worker")
STALE_CHECK_EVERY_S = 60


async def process_once() -> bool:
    """Runs at most one queued job. Returns True if a job was processed."""
    async with SessionLocal() as db:
        job_id = await inference.claim_next(db)
    if job_id is None:
        return False
    async with SessionLocal() as db:
        await inference.run_job(db, job_id)
    return True


async def run_forever(stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    log.info("Inference worker started (ml-service %s)", settings.ml_service_url)
    last_stale_check = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() - last_stale_check > STALE_CHECK_EVERY_S:
                async with SessionLocal() as db:
                    if count := await inference.requeue_stale(db):
                        log.warning("Re-queued or failed %d stale job(s)", count)
                last_stale_check = time.monotonic()
            if await process_once():
                continue
        except Exception:  # noqa: BLE001 - e.g. database restarting; keep the worker alive
            log.exception("Worker loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_s)
        except asyncio.TimeoutError:
            pass
    log.info("Inference worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_forever())
