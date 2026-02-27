from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_llm import DummyLLM


class ModelRegistry:

    def create_embedder(self, config):
        return DummyEmbedder()

    def create_llm(self, config):
        return DummyLLM()