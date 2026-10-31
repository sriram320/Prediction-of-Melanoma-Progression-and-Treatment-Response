"""Adapter registry. Add the teammates' model here: ADAPTERS["<name>"] = TheirAdapter (see model_integration.md §5)."""
import os
from functools import lru_cache
from pathlib import Path

from .base import ModelAdapter
from .mock import MockAdapter

ADAPTERS: dict[str, type] = {"mock": MockAdapter}


@lru_cache(maxsize=1)
def get_adapter() -> ModelAdapter:
    name = os.environ.get("MODEL_ADAPTER", "mock")
    if name not in ADAPTERS:
        raise RuntimeError(f"Unknown MODEL_ADAPTER '{name}'. Known: {sorted(ADAPTERS)}")
    adapter = ADAPTERS[name]()
    adapter.load(Path(os.environ.get("MODEL_DIR", f"/models/{name}/0.1.0")))
    return adapter
