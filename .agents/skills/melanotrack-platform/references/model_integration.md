# Model Integration (ml-service + ModelAdapter)

The trained model is delivered later by the ML teammates. Everything on the web side is built against this
contract, so swapping the mock for the real model means writing **one adapter file** and changing an env var.

## 1. Service boundary
- Container `ml-service` (FastAPI) runs on the internal Docker network only, with no published port.
- `POST /infer` (multipart): a `payload` JSON field matching `LesionSequenceInput`, plus image files named by `image_id`.
- `GET /health` → `{status, adapter, model_name, model_version, is_mock, device:"cuda"|"cpu"}`.
- Caller: `backend/app/workers/inference_worker.py`. It decrypts images to memory (never to disk)
  and sends **only de-identified fields**.
- Timeout: 60 s (NFR-01). Exceeding it raises `model_error`.
- Local dev: `scriptsdevstart_ml_service.ps1` (port 8100). Tests: `cd ml_service; ..ackend.venvScriptspython -m pytest -q tests`.
  The backend suite also mounts this service in-process (`backend/tests/test_analysis.py`), so contract drift fails CI.

## 2. Contract (`ml_service/app/contract.py`, keep identical in `backend/app/schemas/inference.py`; a backend test compares the files)

P3 additions (both backwards compatible): reason code `ambiguous_prediction` (Week 6 Algorithm 4), and optional
per-visit outputs `visits: list[VisitResult]` (Week 8: measured features per visit and an optional single-image
`melanoma_probability`). `change_score` and `uncertainty_score` are bounded to [0, 1]. The listing below is the
P0 draft; the code file is authoritative.
```python
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field

Modality = Literal["dermoscopic", "clinical_photo", "3d_tbp"]
RiskCategory = Literal["routine_monitoring", "shortened_interval", "specialist_referral"]
ReasonCode = Literal["low_image_quality", "registration_uncertain", "model_disagreement",
                     "out_of_distribution", "model_error", "segmentation_low_confidence"]

class ImageInput(BaseModel):
    image_id: str
    modality: Modality
    sha256: str                          # plaintext hash; key for embedding cache
    # bytes arrive as multipart part named image_id; adapter receives a decoded np.ndarray (H,W,3 RGB uint8)

class VisitInput(BaseModel):
    visit_id: str
    visit_date: date
    days_since_baseline: int
    device_model: Optional[str] = None
    illumination: Optional[str] = None
    polarised: Optional[bool] = None
    images: list[ImageInput]

class ClinicalInput(BaseModel):
    age_band: Optional[str] = None
    sex: Optional[str] = None
    anatomical_site: Optional[str] = None
    fitzpatrick_type: Optional[int] = None
    history: dict = {}

class TreatmentInput(BaseModel):
    treatment_type: str
    treatment_date: date

class LesionSequenceInput(BaseModel):
    lesion_ref: str                      # pseudonymous, never the DB lesion id of a named patient
    visits: list[VisitInput]             # sorted ascending by visit_date
    clinical: ClinicalInput
    treatments: list[TreatmentInput] = []

class ImageResult(BaseModel):
    image_id: str
    mask_png_b64: Optional[str] = None
    mask_confidence: Optional[float] = None
    quality_score: Optional[float] = None
    quality_flags: list[str] = []
    registration_transform: Optional[list[list[float]]] = None   # 3x3
    registration_quality: Optional[float] = None

class PredictionOutput(BaseModel):
    model_name: str
    model_version: str
    is_mock: bool
    risk_score: Optional[float] = Field(None, ge=0, le=1)
    risk_category: Optional[RiskCategory] = None
    change_score: Optional[float] = None
    uncertainty_score: Optional[float] = None
    referral_flag: bool = False
    reason_codes: list[ReasonCode] = []
    attention_weights: dict[str, float] = {}      # visit_id -> weight (sum ~1)
    difference_map_png_b64: Optional[str] = None
    saliency_png_b64: Optional[str] = None
    saliency_passed_check: bool = True
    registration_warning: bool = False
    change_summary: list[str] = []                # template sentences, e.g. "Area increased by 18% since baseline"
    modality_mask: dict[str, bool] = {}           # {"dermoscopic":true,"clinical_photo":false,"3d":false,"metadata":true}
    treatment_response: Optional[Literal["favourable","persistent","progression","pending"]] = None
    images: list[ImageResult] = []
```

## 3. Adapter interface (`ml_service/app/adapters/base.py`)
```python
class ModelAdapter(Protocol):
    name: str
    version: str
    is_mock: bool
    def load(self, artifact_dir: Path) -> None: ...
    def predict(self, seq: LesionSequenceInput, images: dict[str, np.ndarray]) -> PredictionOutput: ...
    def health(self) -> dict: ...
```
Selected by env `MODEL_ADAPTER` (`mock` by default). Artifacts live in `MODEL_DIR=/models/<name>/<version>`.
The registry is in `adapters/__init__.py`: `ADAPTERS = {"mock": MockAdapter, ...}`.

## 4. MockAdapter behaviour (deterministic, for UI and demos; numpy + Pillow only)
- Works at 256 px. Segmentation: luminance → Otsu threshold ignoring the dark dermoscope ring (< 30) → largest
  component not touching the border → holes filled; confidence = solidity (area / convex hull).
- Quality: Laplacian variance (blur), bright-pixel ratio (glare).
- Registration: centroid + principal-axis rotation onto the baseline (3x3, original pixels); quality = IoU of the
  **size-normalised** shapes, so genuine growth is not mistaken for misalignment.
- Features per visit: area vs baseline, Lab colour variation, mirror asymmetry, border irregularity (perimeter²/4πA).
- Difference map: ΔE (Lab) between the baseline and the aligned latest image inside the union of masks, colour-mapped
  over the baseline. Saliency: blurred pigment-darkness inside the latest mask (a stand-in for Grad-CAM++).
- risk_score = sigmoid(-2 + 5·growth per 90 days + 1.5·colour-variation change + 2·asymmetry change) ± 0.03 seeded by
  the image hashes (reproducible). ~0 %/yr growth → ~0.12, ~100 %/yr → ~0.3, ~200 %/yr → ~0.6. Category thresholds 0.35 / 0.65.
- Attention: softmax of visit-to-visit change magnitude.
- Referral: image quality < 0.4, registration < 0.5, segmentation confidence < 0.6, uncertainty > 0.35, a score within
  0.015 of a threshold (`ambiguous_prediction`), or no lesion found in a visit.
- `MOCK_FORCE_ERROR=1` raises an exception (used to test the safety wrapper).
- Always returns `is_mock=True`; its version is the last part of `MODEL_DIR`.

## 5. Integrating the real model (checklist)
1. Receive from teammates: weights (TorchScript/ONNX preferred), preprocessing spec, sequence and time-gap
   encoding, segmentation weights + threshold, calibration temperature, category thresholds,
   uncertainty method + referral threshold, conformal quantile, Grad-CAM target layer, `requirements.txt`
   (exact torch/CUDA), 3-5 test sequences with expected outputs, model card + metrics.
2. Copy the files to `ml_service/models/<name>/<version>/` (gitignored; mounted as a volume).
3. Create `ml_service/app/adapters/<name>.py` implementing `ModelAdapter`, mapping their outputs onto `PredictionOutput`.
   Generate `change_summary` from the numeric features with templates (no free text, as in Week 4 M10).
4. Add it to the `ADAPTERS` registry; add torch deps to `ml_service/requirements.txt` (choose the CUDA or CPU wheel).
5. Put the test vectors in `ml_service/tests/vectors/`; `pytest ml_service/tests/test_<name>.py` must match the
   expected outputs within tolerance.
6. Set `MODEL_ADAPTER=<name>`, `MODEL_DIR=/models/<name>/<version>`, then run `docker compose up -d --build ml-service`.
7. `POST /api/v1/models` with metrics + model card, then `POST /models/{id}/activate`. The mock watermark disappears automatically
   because `is_mock=false`.
8. Update the SKILL.md status table (P6).

## 6. Backend safety wrapper (`backend/app/services/inference.py`), applied to every result
```text
if visits_with_valid_images < 2      -> is_baseline=True, risk_score=None, risk_category=None
on exception / timeout / unreachable / validation error -> referral_flag=True, reason_codes=['model_error'], category=None
if output model name/version/is_mock != the active model_versions row -> model_error (watermark must never lie)
if not baseline and no referral and (risk_score or risk_category missing) -> model_error
if any reason code is present        -> referral_flag=True (even if the model forgot the flag)
if any image mask_confidence < SEGMENTATION_CONFIDENCE_THRESHOLD and not mask_confirmed -> referral, add 'segmentation_low_confidence'
if referral_flag                     -> risk_category=None   (DB CHECK also enforces this)
store maps and masks as encrypted stored_files (a doctor-confirmed mask is never overwritten);
write audit 'prediction.create' with model version, outcome and any error
```
Queueing (`POST /lesions/{id}/analyze`): needs recorded consent, a non-excluded visit with scans and an active model;
one queued/running job per lesion (partial unique index). Visits used: non-excluded, with scans, up to the trigger visit.
The input is de-identified: pseudonym-based `lesion_ref`, age band, sex, site, skin type, **yes/no** history only
(free-text notes never leave). Predictions are never replaced: a re-run adds a new row and the newest is "latest".
Worker: `app/workers/inference_worker.py` (`FOR UPDATE SKIP LOCKED`), embedded in the API when `EMBEDDED_WORKER=true`;
a job stuck in `running` for 5 min is re-queued, and failed after 3 attempts.
Embedding cache (NFR-01): the ml-service may cache per-image embeddings keyed by `(image sha256, model_version)`
in `/models/cache/`. The backend sends the sha256 alongside each image so this is possible.
