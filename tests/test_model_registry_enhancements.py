import pytest
from core.registry.model_registry import ModelRegistry
from core.interfaces.llm import BaseLLM
from core.interfaces.embedder import BaseEmbedder
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.simple_embedder import SimpleEmbedder


class CustomMockLLM(BaseLLM):
    def generate(self, prompt: str, config=None) -> str:
        return "Custom response"

    @property
    def context_window(self) -> int:
        return 2048

    @property
    def model_name(self) -> str:
        return "custom-mock"


class CustomMockEmbedder(BaseEmbedder):
    def embed(self, text: str):
        return [0.5] * 32

    @property
    def dimension(self) -> int:
        return 32


def test_registry_custom_llm_provider():
    registry = ModelRegistry("config/models.yaml")
    registry.register_llm_provider("custom", lambda cfg: CustomMockLLM())

    llm = registry.create_llm({"provider": "custom"})
    assert isinstance(llm, CustomMockLLM)
    assert llm.model_name == "custom-mock"
    assert llm.context_window == 2048


def test_registry_custom_embedder_provider():
    registry = ModelRegistry("config/models.yaml")
    registry.register_embedder_provider("custom_emb", lambda cfg: CustomMockEmbedder())

    embedder = registry.create_embedder({"provider": "custom_emb"})
    assert isinstance(embedder, CustomMockEmbedder)
    assert embedder.dimension == 32
    assert len(embedder.embed("test")) == 32


def test_registry_get_embedder_from_config():
    registry = ModelRegistry("config/models.yaml")
    minilm = registry.get_embedder("all-MiniLM-L6-v2")
    assert isinstance(minilm, SimpleEmbedder)
    assert minilm.dimension == 384

    mpnet = registry.get_embedder("all-mpnet-base-v2")
    assert isinstance(mpnet, SimpleEmbedder)
    assert mpnet.dimension == 768


def test_registry_unknown_embedder_raises():
    registry = ModelRegistry("config/models.yaml")
    with pytest.raises(ValueError):
        registry.get_embedder("non_existent_model")
