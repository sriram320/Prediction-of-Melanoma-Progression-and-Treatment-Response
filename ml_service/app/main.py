"""MelanoTrack ml-service. Internal only (no published port); called by the backend inference worker.

POST /infer (multipart): a `payload` field with LesionSequenceInput JSON, plus one file per image named by its
image_id. Responds with PredictionOutput. Any failure is a non-200 response; the backend then stores a referral
with reason `model_error` (NFR-03), so this service never needs to guess a safe default.
"""
import io
import logging
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .adapters import get_adapter
from .contract import LesionSequenceInput, PredictionOutput

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ml-service")
MAX_IMAGES = 64
Image.MAX_IMAGE_PIXELS = 64_000_000

app = FastAPI(title="MelanoTrack ml-service", version="0.1.0", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict:
    adapter = get_adapter()
    return {"status": "ok", "adapter": adapter.name, **adapter.health()}


def _decode(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


@app.post("/infer", response_model=PredictionOutput)
async def infer(request: Request) -> PredictionOutput:
    form = await request.form(max_files=MAX_IMAGES, max_fields=8)
    try:
        seq = LesionSequenceInput.model_validate_json(form.get("payload") or "")
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid payload: {exc.errors()[0]['msg']}") from exc
    wanted = [img.image_id for visit in seq.visits for img in visit.images]
    if not wanted:
        raise HTTPException(422, "The sequence contains no images")
    images: dict[str, np.ndarray] = {}
    for image_id in wanted:
        part = form.get(image_id)
        if part is None or isinstance(part, str):
            raise HTTPException(422, f"Image part '{image_id}' is missing")
        try:
            images[image_id] = await run_in_threadpool(_decode, await part.read())
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(422, f"Image '{image_id}' cannot be decoded") from exc

    adapter = get_adapter()
    started = time.perf_counter()
    try:
        result = await run_in_threadpool(adapter.predict, seq, images)
    except Exception as exc:  # reported to the backend, which turns it into a referral
        log.exception("Adapter %s failed", adapter.name)
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
    log.info("Inferred %d visits / %d images in %.0f ms", len(seq.visits), len(images),
             (time.perf_counter() - started) * 1000)
    return result
