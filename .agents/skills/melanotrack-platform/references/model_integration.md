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

## 2. Contract (`ml_service/app/contract.py`, keep identical in `backend/app/schemas/inference.py`)
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

## 4. MockAdapter behaviour (deterministic, for UI and demos)
- Segmentation: grayscale → Otsu threshold → largest contour → mask; confidence = contour solidity.
- Quality: Laplacian variance (blur), bright-pixel ratio (glare).
- Registration: centroid + principal-axis alignment of masks; quality = warped-mask IoU.
- Difference map: ΔE (Lab) inside the union of masks, colour-mapped PNG.
- risk_score = sigmoid(k · relative area growth per 90 days + colour-variance change), seeded by the image hash
  so that results are reproducible.
- Attention: softmax of per-visit change magnitude.
- Referral: if quality is low, registration IoU < 0.5, or uncertainty > 0.35.
- `MOCK_FORCE_ERROR=1` raises an exception (used to test the safety wrapper).
- Always returns `is_mock=True`.

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
on exception / timeout / validation error -> referral_flag=True, reason_codes=['model_error'], category=None
if any image mask_confidence < SEG_THRESHOLD and not mask_confirmed -> referral_flag=True, add 'segmentation_low_confidence'
if referral_flag                     -> risk_category=None   (DB CHECK also enforces this)
store maps as encrypted stored_files; write audit 'prediction.create' with model version
```
Embedding cache (NFR-01): the ml-service may cache per-image embeddings keyed by `(image sha256, model_version)`
in `/models/cache/`. The backend sends the sha256 alongside each image so this is possible.
