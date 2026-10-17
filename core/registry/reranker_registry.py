from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from core.interfaces.reranker import BaseReranker


class RerankerRegistry:
    """
    Configuration-driven registry and factory for rerankers.

    Reads the ``reranking`` block from config/retrieval.yaml:

        reranking:
          enabled: true
          strategy: lexical_hybrid
          lexical_weight: 0.6
          initial_score_weight: 0.4
          top_k: 3
          active_reranker: simple      # optional, defaults to 'simple'
          rerankers:                   # optional named providers
            simple: {provider: simple}
            dummy:  {provider: dummy}
            none:   {provider: none}

    Setting ``enabled: false`` makes ``create()`` return ``None`` so the pipeline
    skips the reranking stage entirely (latency/observability then reflect the skip).

    Adding a new reranker follows the blueprint's customization path: implement
    ``BaseReranker`` in ``core/implementations`` and register a provider here (or
    via ``register``). The composition root (``app/main.py``) only depends on this
    registry, never on a concrete reranker, so backends can be swapped by config.
    """

    _SIMPLE_OPTIONS = {
        "strategy",
        "lexical_weight",
        "initial_score_weight",
        "top_k",
        "scoring_fn",
    }

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self._providers: Dict[str, Callable[..., Optional[BaseReranker]]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register("simple", self._build_simple)
        self.register("cross_encoder", self._build_cross_encoder)
        self.register("dummy", self._build_dummy)
        self.register("noop", self._build_none)
        self.register("none", self._build_none)

    def _build_simple(self, **options: Any) -> BaseReranker:
        from core.implementations.simple_reranker import SimpleReranker

        config_path = options.pop("config_path", None) or self.config_path
        kwargs = {k: v for k, v in options.items() if k in self._SIMPLE_OPTIONS}
        return SimpleReranker(config_path=config_path, **kwargs)

    @staticmethod
    def _build_cross_encoder(**options: Any) -> BaseReranker:
        from core.implementations.cross_encoder_reranker import CrossEncoderReranker

        model_name = options.get("model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        top_k = options.get("top_k")
        return CrossEncoderReranker(model_name=model_name, top_k=top_k)

    @staticmethod
    def _build_dummy(**options: Any) -> BaseReranker:
        from core.implementations.dummy_reranker import DummyReranker

        return DummyReranker(reverse=bool(options.get("reverse", False)))

    @staticmethod
    def _build_none(**_options: Any) -> Optional[BaseReranker]:
        return None

    def register(
        self,
        provider_name: str,
        factory: Callable[..., Optional[BaseReranker]],
    ) -> None:
        """
        Register a reranker provider factory. Enables third-party plug-ins
        without modifying registry logic.
        """
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def list_rerankers(self) -> List[str]:
        return sorted((self.config.get("reranking") or {}).get("rerankers", {}).keys())

    def is_enabled(self) -> bool:
        reranking = self.config.get("reranking") or {}
        return bool(reranking.get("enabled", True))

    def resolve(self, name: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        """
        Resolve a reranker key to (key, provider, provider_config) using config.
        """
        reranking = self.config.get("reranking") or {}
        rerankers = reranking.get("rerankers") or {}

        key = name if name is not None else reranking.get("active_reranker", "simple")
        if not key:
            raise ValueError("No reranker specified and 'reranking.active_reranker' is missing.")

        if key in rerankers and isinstance(rerankers[key], dict):
            entry = dict(rerankers[key])
            provider = str(entry.get("provider", key)).lower()
        else:
            entry = {}
            provider = str(key).lower()

        if provider not in self._providers:
            raise ValueError(
                f"Unknown reranker provider: '{provider}'. "
                f"Registered providers: {self.list_providers()}"
            )
        return str(key), provider, entry

    def create(
        self, name: Optional[str] = None, enabled: Optional[bool] = None, **overrides: Any
    ) -> Optional[BaseReranker]:
        if enabled is None:
            enabled = self.is_enabled()
        if not enabled:
            return None

        _key, provider, entry = self.resolve(name)
        options = {**entry, **overrides}
        options.pop("provider", None)
        return self._providers[provider](**options)
