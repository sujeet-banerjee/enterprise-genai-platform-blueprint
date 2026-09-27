import yaml
from typing import Dict, Any, Callable, Optional, Union
from core.interfaces.llm import BaseLLM
from core.interfaces.embedder import BaseEmbedder
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.openai_llm import OpenAILLM
from core.implementations.simple_embedder import SimpleEmbedder


class ModelRegistry:
    """
    Abstracted registry for LLM and Embedder models.
    Maps configuration providers to model implementations.
    """

    def __init__(self, config_or_path: Union[str, dict] = "config/models.yaml"):
        if isinstance(config_or_path, str):
            self.config_path = config_or_path
            with open(config_or_path, "r") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config_path = None
            self.config = config_or_path or {}

        # Default provider factory maps
        self._llm_providers: Dict[str, Callable[[Dict[str, Any]], BaseLLM]] = {}
        self._embedder_providers: Dict[str, Callable[[Dict[str, Any]], BaseEmbedder]] = {}

        # Register standard built-in providers
        self._register_default_providers()

    def _register_default_providers(self):
        self.register_llm_provider("dummy", lambda cfg: DummyLLM())
        self.register_llm_provider("openai", lambda cfg: OpenAILLM(api_key=cfg.get("api_key", "dummy")))
        self.register_llm_provider("local", lambda cfg: DummyLLM())

        self.register_embedder_provider("dummy", lambda cfg: DummyEmbedder())
        self.register_embedder_provider(
            "sentence-transformers",
            lambda cfg: SimpleEmbedder(model_name=cfg.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"))
        )
        self.register_embedder_provider(
            "simple",
            lambda cfg: SimpleEmbedder(model_name=cfg.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"))
        )

    def register_llm_provider(self, provider_name: str, factory_fn: Callable[[Dict[str, Any]], BaseLLM]):
        """
        Register a new LLM provider factory function or class.
        """
        self._llm_providers[provider_name.lower()] = factory_fn

    def register_embedder_provider(self, provider_name: str, factory_fn: Callable[[Dict[str, Any]], BaseEmbedder]):
        """
        Register a new Embedder provider factory function or class.
        """
        self._embedder_providers[provider_name.lower()] = factory_fn

    def create_llm(self, model_config: Dict[str, Any]) -> BaseLLM:
        provider = model_config.get("provider", "").lower()
        if not provider:
            raise ValueError("Model configuration missing 'provider' field.")
        if provider not in self._llm_providers:
            raise ValueError(f"Unknown provider: {provider}")
        return self._llm_providers[provider](model_config)

    def create_embedder(self, embedder_config: Dict[str, Any]) -> BaseEmbedder:
        provider = embedder_config.get("provider", "").lower()
        if not provider:
            raise ValueError("Embedder configuration missing 'provider' field.")
        if provider not in self._embedder_providers:
            raise ValueError(f"Unknown embedder provider: {provider}")
        return self._embedder_providers[provider](embedder_config)

    def get_model(self, model_name: Optional[str] = None) -> BaseLLM:
        target_name = model_name or self.config.get("active_model")
        if not target_name:
            raise ValueError("No active model specified in configuration.")

        models_section = self.config.get("models", {})
        if target_name not in models_section:
            raise ValueError(
                f"Invalid model: {target_name}; no such model found in config: {self.config_path}"
            )

        model_config = models_section[target_name]
        return self.create_llm(model_config)

    def get_active_model(self) -> BaseLLM:
        return self.get_model()

    def get_embedder(self, model_name: Optional[str] = None) -> BaseEmbedder:
        target_name = model_name or self.config.get("active_embedding_model")
        if not target_name:
            # Fallback to first available or active_model
            embedding_models = self.config.get("embedding_models", {})
            if embedding_models:
                target_name = next(iter(embedding_models.keys()))
            else:
                return DummyEmbedder()

        embedding_models = self.config.get("embedding_models", {})
        if target_name not in embedding_models:
            raise ValueError(
                f"Invalid embedding model: {target_name}; not found in config: {self.config_path}"
            )

        embedder_config = embedding_models[target_name]
        return self.create_embedder(embedder_config)

    def get_active_embedder(self) -> BaseEmbedder:
        return self.get_embedder()
