"""Tests for config-driven embedding-model selection in SimpleEmbedder (issue #1).

The embedder must pick its model from ``config/models.yaml`` (via
``active_embedding_model`` and the ``embedding_models`` map) and expose a
``model_name`` option at construction time. No model name is hardcoded: an
unconfigured embedder raises instead of silently defaulting to a fixed model.
"""

import pytest
import yaml

import core.implementations.simple_embedder as simple_embedder_module
from core.implementations.simple_embedder import SimpleEmbedder
from core.registry.model_registry import ModelRegistry


class _FakeModel:
    """Minimal SentenceTransformer stand-in so tests never touch the network."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def get_sentence_embedding_dimension(self) -> int:
        return 8

    def encode(self, text: str):
        return [0.25] * 8


def _capture_loaded_names(monkeypatch):
    seen = {}

    def fake_get_sentence_transformer(model_name, local_files_only=True):
        seen["model_name"] = model_name
        seen["local_files_only"] = local_files_only
        return _FakeModel(model_name)

    monkeypatch.setattr(
        simple_embedder_module, "get_sentence_transformer", fake_get_sentence_transformer
    )
    return seen


def _write_config(tmp_path, data):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def test_uses_active_embedding_model_from_config(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "some-key",
            "embedding_models": {
                "some-key": {"provider": "sentence_transformers", "model_name": "org/some-model"}
            },
        },
    )

    embedder = SimpleEmbedder(config_path=config_path)

    assert seen["model_name"] == "org/some-model"
    assert embedder.model_name == "org/some-model"


def test_explicit_model_name_overrides_active_embedding_model(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "some-key",
            "embedding_models": {"some-key": {"model_name": "org/some-model"}},
        },
    )

    SimpleEmbedder(model_name="org/explicit-model", config_path=config_path)

    assert seen["model_name"] == "org/explicit-model"


def test_string_embedding_model_entry_is_used(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "stringy",
            "embedding_models": {"stringy": "org/string-model"},
        },
    )

    SimpleEmbedder(config_path=config_path)

    assert seen["model_name"] == "org/string-model"


def test_entry_without_model_name_falls_back_to_key(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "org/key-as-name",
            "embedding_models": {"org/key-as-name": {"provider": "sentence_transformers"}},
        },
    )

    SimpleEmbedder(config_path=config_path)

    assert seen["model_name"] == "org/key-as-name"


def test_short_name_is_resolved_through_config(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "all-MiniLM-L6-v2",
            "embedding_models": {
                "all-MiniLM-L6-v2": {
                    "provider": "sentence_transformers",
                    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                }
            },
        },
    )

    embedder = SimpleEmbedder(config_path=config_path)

    assert seen["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert embedder.model_name == "sentence-transformers/all-MiniLM-L6-v2"


def test_missing_active_embedding_model_raises_without_hardcoded_default(tmp_path, monkeypatch):
    _capture_loaded_names(monkeypatch)
    config_path = _write_config(tmp_path, {"embedding_models": {}})

    with pytest.raises(ValueError, match="No embedding model specified"):
        SimpleEmbedder(config_path=config_path)


def test_unreadable_config_without_model_name_raises(tmp_path, monkeypatch):
    _capture_loaded_names(monkeypatch)

    with pytest.raises(ValueError, match="No embedding model specified"):
        SimpleEmbedder(config_path=str(tmp_path / "does-not-exist.yaml"))


def test_registry_embedder_requires_active_embedding_model(tmp_path):
    config_path = _write_config(tmp_path, {"embedding_models": {}})
    registry = ModelRegistry(config_path)

    with pytest.raises(ValueError, match="No embedding model specified"):
        registry.get_embedder()


def test_registry_resolves_selected_embedding_model(tmp_path, monkeypatch):
    seen = _capture_loaded_names(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "active_embedding_model": "chosen",
            "embedding_models": {
                "chosen": {"provider": "sentence_transformers", "model_name": "org/chosen-model"}
            },
        },
    )
    registry = ModelRegistry(config_path)

    embedder = registry.get_embedder()

    assert seen["model_name"] == "org/chosen-model"
    assert embedder.model_name == "org/chosen-model"
