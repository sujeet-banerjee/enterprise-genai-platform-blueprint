import pytest
from core.registry.model_registry import ModelRegistry
from core.implementations.dummy_llm import DummyLLM
from core.implementations.simple_embedder import SimpleEmbedder
from core.interfaces.llm import BaseLLM
from core.interfaces.embedder import BaseEmbedder


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


def test_registry_plug_and_play_custom_llm_and_embedder():
    registry = ModelRegistry("config/models.yaml")

    class CustomLLM(BaseLLM):
        def generate(self, prompt: str, config=None) -> str:
            return f"custom:{prompt}"

        @property
        def context_window(self) -> int:
            return 16384

        @property
        def model_name(self) -> str:
            return "custom-enterprise-llm"

    class CustomEmbedder(BaseEmbedder):
        def embed(self, text: str):
            return [0.5] * 16

        @property
        def dimension(self) -> int:
            return 16

    registry.register_model(
        "enterprise-custom",
        {"provider": "custom_vendor", "context_window": 16384},
        factory=lambda name, cfg: CustomLLM(),
    )
    registry.register_embedding_model(
        "enterprise-embed",
        {"provider": "custom_embed_vendor", "model_name": "enterprise-embed"},
        factory=lambda name, cfg: CustomEmbedder(),
    )

    llm = registry.get_model("enterprise-custom")
    emb = registry.get_embedder("enterprise-embed")
    assert isinstance(llm, CustomLLM)
    assert llm.context_window == 16384
    assert isinstance(emb, CustomEmbedder)
    assert emb.dimension == 16


def test_registry_loads_configured_embedding_models():
    registry = ModelRegistry("config/models.yaml")
    minilm = registry.get_embedder("all-MiniLM-L6-v2")
    mpnet = registry.get_embedder("all-mpnet-base-v2")
    assert isinstance(minilm, SimpleEmbedder)
    assert isinstance(mpnet, SimpleEmbedder)
    assert minilm.dimension == 384
    assert mpnet.dimension == 768


def test_registry_invalid_model_raises():
    registry = ModelRegistry("config/models.yaml")
    with pytest.raises(ValueError):
        registry.get_model("non_existent_model_xyz")
    with pytest.raises(ValueError):
        registry.get_embedder("non_existent_embedder_xyz")
