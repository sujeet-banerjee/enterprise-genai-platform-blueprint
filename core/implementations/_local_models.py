"""Process-wide caches for locally-loaded HuggingFace models.

Loading a transformer is expensive (seconds to minutes) and deterministic, so a
single loaded instance is shared across every component and test that needs it.
Models are imported lazily so that importing this module never triggers a heavy
``transformers`` import (important for fast startup and cheap unit tests).

All models used by the blueprint are public, so no credential is required. If an
``HF_TOKEN`` environment variable is present it is forwarded to the Hub, which
raises rate limits and unlocks gated repositories; when absent the calls proceed
anonymously.
"""

import os
from typing import Any, Dict, Optional

_TEXT_GENERATION_CACHE: Dict[str, Any] = {}
_CROSS_ENCODER_CACHE: Dict[str, Any] = {}
_SENTENCE_TRANSFORMER_CACHE: Dict[str, Any] = {}


def _hf_token() -> Optional[str]:
    """Return the configured HuggingFace token, or ``None`` when unset."""
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    return token or None


def get_sentence_transformer(model_name: str, local_files_only: bool = True) -> Any:
    """Return a cached ``SentenceTransformer`` for ``model_name``.

    Embedders and evaluators frequently point at the same underlying model
    (for example ``all-MiniLM-L6-v2``), so a single loaded instance is shared
    process-wide rather than re-loading weights for every component.
    """
    cache_key = f"{model_name}::{local_files_only}"
    if cache_key not in _SENTENCE_TRANSFORMER_CACHE:
        from sentence_transformers import SentenceTransformer

        _SENTENCE_TRANSFORMER_CACHE[cache_key] = SentenceTransformer(
            model_name, local_files_only=local_files_only, token=_hf_token()
        )
    return _SENTENCE_TRANSFORMER_CACHE[cache_key]


def get_text_generation_pipeline(model_name: str) -> Any:
    """Return a cached HuggingFace text-generation pipeline for ``model_name``."""
    if model_name not in _TEXT_GENERATION_CACHE:
        from transformers import pipeline

        _TEXT_GENERATION_CACHE[model_name] = pipeline(
            "text-generation", model=model_name, token=_hf_token()
        )
    return _TEXT_GENERATION_CACHE[model_name]


def get_cross_encoder(model_name: str) -> Any:
    """Return a cached sentence-transformers ``CrossEncoder`` for ``model_name``."""
    if model_name not in _CROSS_ENCODER_CACHE:
        from sentence_transformers import CrossEncoder

        _CROSS_ENCODER_CACHE[model_name] = CrossEncoder(model_name, token=_hf_token())
    return _CROSS_ENCODER_CACHE[model_name]
