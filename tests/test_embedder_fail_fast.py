"""Tests for issue #18: an unloadable configured embedding model must fail fast
with a structured error instead of silently fabricating embeddings.

Acceptance criteria:
1. A missing/unloadable configured model raises a clear, structured error.
2. No implicit fabricated embeddings unless the caller explicitly opts in.
"""

import pytest
import yaml

import core.implementations.simple_embedder as simple_embedder_module
from core.implementations.simple_embedder import (
    EmbeddingModelLoadError,
    SimpleEmbedder,
    _LocalSentenceEncoder,
)
from core.registry.model_registry import ModelRegistry


def _raise_loader(*_args, **_kwargs):
    raise OSError("simulated offline / hub unreachable")


def _patch_loader(monkeypatch):
    monkeypatch.setattr(simple_embedder_module, "get_sentence_transformer", _raise_loader)


def _write_models_config(tmp_path, entry: dict, top_level: bool | None = None) -> str:
    payload: dict = {
        "active_embedding_model": "custom",
        "embedding_models": {"custom": entry},
    }
    if top_level is not None:
        payload["allow_offline_fallback"] = top_level
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def test_unloadable_model_raises_structured_error(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path, {"provider": "sentence_transformers", "model_name": "custom-model"}
    )

    with pytest.raises(EmbeddingModelLoadError) as excinfo:
        SimpleEmbedder(model_name="custom", config_path=config_path)

    error = excinfo.value
    assert isinstance(error, RuntimeError)
    assert error.model_name == "custom-model"
    assert "custom-model" in str(error)
    assert isinstance(error.download_error, OSError)
    assert isinstance(error.local_error, OSError)


def test_no_offline_fallback_by_default(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path, {"provider": "sentence_transformers", "model_name": "custom-model"}
    )
    with pytest.raises(EmbeddingModelLoadError):
        SimpleEmbedder(model_name="custom", config_path=config_path)


def test_explicit_opt_in_uses_offline_fallback(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path, {"provider": "sentence_transformers", "model_name": "custom-model"}
    )

    embedder = SimpleEmbedder(
        model_name="custom", config_path=config_path, allow_offline_fallback=True
    )
    assert embedder.allow_offline_fallback is True
    assert isinstance(embedder.model, _LocalSentenceEncoder)
    vector = embedder.embed("hello world")
    assert len(vector) == embedder.dimension


def test_config_per_model_opt_in_enables_fallback(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path,
        {
            "provider": "sentence_transformers",
            "model_name": "custom-model",
            "allow_offline_fallback": True,
        },
    )

    embedder = SimpleEmbedder(model_name="custom", config_path=config_path)
    assert embedder.allow_offline_fallback is True
    assert isinstance(embedder.model, _LocalSentenceEncoder)


def test_top_level_config_opt_in_enables_fallback(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path,
        {"provider": "sentence_transformers", "model_name": "custom-model"},
        top_level=True,
    )

    embedder = SimpleEmbedder(model_name="custom", config_path=config_path)
    assert isinstance(embedder.model, _LocalSentenceEncoder)


def test_explicit_false_overrides_config_opt_in(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path,
        {
            "provider": "sentence_transformers",
            "model_name": "custom-model",
            "allow_offline_fallback": True,
        },
    )

    with pytest.raises(EmbeddingModelLoadError):
        SimpleEmbedder(model_name="custom", config_path=config_path, allow_offline_fallback=False)


def test_model_registry_propagates_offline_fallback_entry(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path,
        {
            "provider": "sentence_transformers",
            "model_name": "custom-model",
            "allow_offline_fallback": True,
        },
    )

    embedder = ModelRegistry(config_path).get_embedder("custom")
    assert isinstance(embedder.model, _LocalSentenceEncoder)


def test_model_registry_fails_fast_by_default(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    config_path = _write_models_config(
        tmp_path, {"provider": "sentence_transformers", "model_name": "custom-model"}
    )

    with pytest.raises(EmbeddingModelLoadError):
        ModelRegistry(config_path).get_embedder("custom")
