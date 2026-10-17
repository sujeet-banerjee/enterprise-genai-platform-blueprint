"""Process-wide caches for locally-loaded HuggingFace models.

Loading a transformer is expensive (seconds to minutes) and deterministic, so a
single loaded instance is shared across every component and test that needs it.
Models are imported lazily so that importing this module never triggers a heavy
``transformers`` import (important for fast startup and cheap unit tests).
"""

from typing import Any, Dict

_TEXT_GENERATION_CACHE: Dict[str, Any] = {}
_CROSS_ENCODER_CACHE: Dict[str, Any] = {}


def get_text_generation_pipeline(model_name: str) -> Any:
    """Return a cached HuggingFace text-generation pipeline for ``model_name``."""
    if model_name not in _TEXT_GENERATION_CACHE:
        from transformers import pipeline

        _TEXT_GENERATION_CACHE[model_name] = pipeline("text-generation", model=model_name)
    return _TEXT_GENERATION_CACHE[model_name]


def get_cross_encoder(model_name: str) -> Any:
    """Return a cached sentence-transformers ``CrossEncoder`` for ``model_name``."""
    if model_name not in _CROSS_ENCODER_CACHE:
        from sentence_transformers import CrossEncoder

        _CROSS_ENCODER_CACHE[model_name] = CrossEncoder(model_name)
    return _CROSS_ENCODER_CACHE[model_name]
