"""HTTP client for the ml-service. Every failure becomes ModelCallError, which the safety wrapper turns into a
referral. Tests replace `transport` with an in-process one."""
import asyncio

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.inference import LesionSequenceInput, PredictionOutput

transport: httpx.AsyncBaseTransport | None = None


class ModelCallError(Exception):
    pass


async def infer(seq: LesionSequenceInput, images: dict[str, tuple[bytes, str]]) -> PredictionOutput:
    files = [(image_id, (image_id, data, mime)) for image_id, (data, mime) in images.items()]

    async def call() -> PredictionOutput:
        async with httpx.AsyncClient(base_url=settings.ml_service_url, transport=transport,
                                     timeout=settings.inference_timeout_s + 5) as client:
            response = await client.post("/infer", data={"payload": seq.model_dump_json()}, files=files)
        if response.status_code != 200:
            raise ModelCallError(f"ml-service returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            return PredictionOutput.model_validate_json(response.content)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise ModelCallError(f"Invalid model output at {'.'.join(map(str, first['loc']))}: {first['msg']}")

    try:
        return await asyncio.wait_for(call(), timeout=settings.inference_timeout_s)
    except asyncio.TimeoutError as exc:
        raise ModelCallError(f"No result within {settings.inference_timeout_s} s") from exc
    except httpx.HTTPError as exc:
        raise ModelCallError(f"ml-service unreachable ({type(exc).__name__})") from exc
