from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import yaml

from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_llm import DummyLLM
from core.implementations.openai_llm import OpenAILLM
from core.implementations.simple_embedder import SimpleEmbedder
from core.interfaces.embedder import BaseEmbedder
from core.interfaces.llm import BaseLLM


class _ConfigurableDummyLLM(DummyLLM):
    """
    Dummy/local LLM wrapper that honors context_window and model_name from configuration.
    """

    def __init__(self, model_name: str = "dummy-llm", context_window: int = 4096, **kwargs):
        self._model_name = model_name
        self._context_window = int(context_window)
        self.extra_config = kwargs

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def model_name(self) -> str:
        return self._model_name


class ModelRegistry:
    """
    Configuration-driven registry and factory for LLM and Embedding models.
    Replaces scattered conditional logic with a pluggable provider/model registry map.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self._llm_providers: Dict[str, Callable[[str, Dict[str, Any]], BaseLLM]] = {}
        self._embedder_providers: Dict[str, Callable[[str, Dict[str, Any]], BaseEmbedder]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register_llm_provider(
            "dummy",
            lambda name, cfg: DummyLLM()
            if name == "dummy" and cfg.get("context_window", 4096) == 4096
            else _ConfigurableDummyLLM(
                model_name=name,
                context_window=cfg.get("context_window", 4096),
            ),
        )
        self.register_llm_provider(
            "local",
            lambda name, cfg: _ConfigurableDummyLLM(
                model_name=name,
                context_window=cfg.get("context_window", 8192),
            ),
        )
        self.register_llm_provider(
            "openai",
            lambda name, cfg: OpenAILLM(api_key=cfg.get("api_key", "dummy")),
        )

        self.register_embedder_provider(
            "dummy",
            lambda name, cfg: DummyEmbedder(
                model_name=cfg.get("model_name", name),
            ),
        )
        self.register_embedder_provider(
            "sentence_transformers",
            lambda name, cfg: SimpleEmbedder(
                model_name=cfg.get("model_name", name),
                config_path=self.config_path,
            ),
        )
        self.register_embedder_provider(
            "local",
            lambda name, cfg: SimpleEmbedder(
                model_name=cfg.get("model_name", name),
                config_path=self.config_path,
            ),
        )
        self.register_embedder_provider(
            "huggingface",
            lambda name, cfg: SimpleEmbedder(
                model_name=cfg.get("model_name", name),
                config_path=self.config_path,
            ),
        )

    def register_llm_provider(
        self,
        provider_name: str,
        factory: Callable[..., BaseLLM],
    ) -> None:
        def _wrapped(name: str, cfg: Dict[str, Any]) -> BaseLLM:
            try:
                return factory(name, cfg)
            except TypeError:
                try:
                    return factory(**cfg)
                except TypeError:
                    return factory()

        self._llm_providers[provider_name.lower()] = _wrapped

    def register_provider(
        self,
        provider_name: str,
        factory: Callable[..., BaseLLM],
    ) -> None:
        self.register_llm_provider(provider_name, factory)

    def register_embedder_provider(
        self,
        provider_name: str,
        factory: Callable[..., BaseEmbedder],
    ) -> None:
        def _wrapped(name: str, cfg: Dict[str, Any]) -> BaseEmbedder:
            try:
                return factory(name, cfg)
            except TypeError:
                try:
                    return factory(**cfg)
                except TypeError:
                    return factory()

        self._embedder_providers[provider_name.lower()] = _wrapped

    def register_model(
        self,
        model_name: str,
        model_config: Dict[str, Any],
        factory: Optional[Callable[..., BaseLLM]] = None,
    ) -> None:
        if "models" not in self.config or self.config["models"] is None:
            self.config["models"] = {}
        self.config["models"][model_name] = dict(model_config)
        if factory is not None:
            provider = model_config.get("provider", model_name)
            self.register_llm_provider(provider, factory)

    def register_embedding_model(
        self,
        model_name: str,
        model_config: Dict[str, Any],
        factory: Optional[Callable[..., BaseEmbedder]] = None,
    ) -> None:
        if "embedding_models" not in self.config or self.config["embedding_models"] is None:
            self.config["embedding_models"] = {}
        self.config["embedding_models"][model_name] = dict(model_config)
        if factory is not None:
            provider = model_config.get("provider", model_name)
            self.register_embedder_provider(provider, factory)

    def list_models(self) -> List[str]:
        return list((self.config.get("models") or {}).keys())

    def list_embedding_models(self) -> List[str]:
        return list((self.config.get("embedding_models") or {}).keys())

    def get_model(self, model_name: Optional[str] = None) -> BaseLLM:
        target_name = model_name or self.config.get("active_model")
        models_map = self.config.get("models") or {}
        if not target_name or target_name not in models_map:
            raise ValueError(
                f"Invalid model: {target_name}; no such model found in config file: {self.config_path}"
            )

        model_config = models_map[target_name] or {}
        provider = str(model_config.get("provider", "")).lower()

        if provider not in self._llm_providers:
            raise ValueError(f"Unknown provider: {provider}")

        return self._llm_providers[provider](target_name, model_config)

    def get_active_model(self) -> BaseLLM:
        return self.get_model(self.config.get("active_model"))

    def get_embedder(self, model_name: Optional[str] = None) -> BaseEmbedder:
        target_name = model_name or self.config.get("active_embedding_model", "all-MiniLM-L6-v2")
        emb_map = self.config.get("embedding_models") or {}

        if target_name in emb_map and isinstance(emb_map[target_name], dict):
            emb_config = dict(emb_map[target_name])
            provider = str(emb_config.get("provider", "sentence_transformers")).lower()
        elif target_name == "dummy":
            emb_config = {"provider": "dummy", "model_name": "dummy-embedder"}
            provider = "dummy"
        elif target_name in ("all-MiniLM-L6-v2", "all-mpnet-base-v2") or str(target_name).startswith("sentence-transformers/"):
            emb_config = {"provider": "sentence_transformers", "model_name": target_name}
            provider = "sentence_transformers"
        else:
            raise ValueError(
                f"Invalid embedding model: {target_name}; no such embedding model found in config file: {self.config_path}"
            )

        if provider not in self._embedder_providers:
            raise ValueError(f"Unknown embedding provider: {provider}")

        return self._embedder_providers[provider](target_name, emb_config)

    def get_active_embedder(self) -> BaseEmbedder:
        return self.get_embedder(self.config.get("active_embedding_model"))

    def create_llm(self, config: Optional[Union[str, Dict[str, Any]]] = None) -> BaseLLM:
        if isinstance(config, str):
            return self.get_model(config)
        if isinstance(config, dict):
            if "model_name" in config and config["model_name"] in (self.config.get("models") or {}):
                return self.get_model(config["model_name"])
            provider = str(config.get("provider", "dummy")).lower()
            if provider not in self._llm_providers:
                raise ValueError(f"Unknown provider: {provider}")
            return self._llm_providers[provider](config.get("model_name", "dummy"), config)
        return self.get_active_model()

    def create_embedder(self, config: Optional[Union[str, Dict[str, Any]]] = None) -> BaseEmbedder:
        if isinstance(config, str):
            return self.get_embedder(config)
        if isinstance(config, dict):
            if "model_name" in config and config["model_name"] in (self.config.get("embedding_models") or {}):
                return self.get_embedder(config["model_name"])
            provider = str(config.get("provider", "dummy")).lower()
            if provider not in self._embedder_providers:
                raise ValueError(f"Unknown embedding provider: {provider}")
            return self._embedder_providers[provider](config.get("model_name", "dummy"), config)
        return DummyEmbedder()
