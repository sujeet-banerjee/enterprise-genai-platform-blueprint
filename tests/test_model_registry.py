import pytest
from core.registry.model_registry import ModelRegistry
from core.implementations.dummy_llm import DummyLLM


def test_registry_loads_config():
    registry = ModelRegistry("config/models.yaml")
    assert registry.config is not None


def test_registry_returns_active_model():
    registry = ModelRegistry("config/models.yaml")
    model = registry.get_active_model()
    assert isinstance(model, DummyLLM)


def test_registry_unknown_provider():
    registry = ModelRegistry("config/models.yaml")
    registry.config["models"]["dummy"]["provider"] = "unknown"
    with pytest.raises(ValueError):
        registry.get_active_model()