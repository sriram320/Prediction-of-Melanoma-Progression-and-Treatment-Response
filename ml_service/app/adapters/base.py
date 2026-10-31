from pathlib import Path
from typing import Protocol

import numpy as np

from ..contract import LesionSequenceInput, PredictionOutput


class ModelAdapter(Protocol):
    """Wraps one trained model. `images` maps image_id -> decoded RGB uint8 array (H, W, 3)."""

    name: str
    version: str
    is_mock: bool

    def load(self, artifact_dir: Path) -> None: ...

    def predict(self, seq: LesionSequenceInput, images: dict[str, np.ndarray]) -> PredictionOutput: ...

    def health(self) -> dict: ...
