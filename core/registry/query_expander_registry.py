from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from core.interfaces.query_expander import BaseQueryExpander


class QueryExpanderRegistry:
    """
    Configuration-driven registry and factory for query expanders (issue #23).

    Reads the ``query_expansion`` block from config/retrieval.yaml:

        query_expansion:
          enabled: false
          active_expander: synonym
          max_variants: 3
          expanders:
            noop:    {provider: noop}
            synonym:
              provider: synonym
              max_variants: 3
              synonyms:
                ai: [artificial intelligence]
            llm:     {provider: llm}

    ``enabled: false`` (the default) makes ``create()`` return ``None`` so the
    pipeline skips expansion entirely and behaviour is unchanged.
    """

    _SYNONYM_OPTIONS = {"synonyms", "max_variants", "include_original"}
    _LLM_OPTIONS = {"llm", "max_variants", "max_new_tokens"}

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self._providers: Dict[str, Callable[..., Optional[BaseQueryExpander]]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register("noop", self._build_noop)
        self.register("synonym", self._build_synonym)
        self.register("llm", self._build_llm)

    @staticmethod
    def _build_noop(**_options: Any) -> BaseQueryExpander:
        from core.implementations.query_expanders import NoopQueryExpander

        return NoopQueryExpander()

    def _build_synonym(self, **options: Any) -> BaseQueryExpander:
        from core.implementations.query_expanders import SynonymQueryExpander

        kwargs = {k: v for k, v in options.items() if k in self._SYNONYM_OPTIONS}
        return SynonymQueryExpander(**kwargs)

    def _build_llm(self, **options: Any) -> BaseQueryExpander:
        from core.implementations.query_expanders import LLMQueryExpander

        kwargs = {k: v for k, v in options.items() if k in self._LLM_OPTIONS}
        return LLMQueryExpander(**kwargs)

    def register(
        self,
        provider_name: str,
        factory: Callable[..., Optional[BaseQueryExpander]],
    ) -> None:
        """Register a query-expander provider factory (third-party plug-ins)."""
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def list_expanders(self) -> List[str]:
        section = self.config.get("query_expansion") or {}
        return sorted((section.get("expanders") or {}).keys())

    def is_enabled(self) -> bool:
        section = self.config.get("query_expansion") or {}
        return bool(section.get("enabled", False))

    def resolve(self, name: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        section = self.config.get("query_expansion") or {}
        expanders = section.get("expanders") or {}

        key = name if name is not None else section.get("active_expander", "synonym")
        if not key:
            raise ValueError(
                "No expander specified and 'query_expansion.active_expander' is missing."
            )

        if key in expanders and isinstance(expanders[key], dict):
            entry = dict(expanders[key])
            provider = str(entry.get("provider", key)).lower()
        else:
            entry = {}
            provider = str(key).lower()

        # Section-level default variants fill in unless the entry overrides it.
        if "max_variants" not in entry and section.get("max_variants") is not None:
            entry["max_variants"] = section["max_variants"]

        if provider not in self._providers:
            raise ValueError(
                f"Unknown query-expander provider: '{provider}'. "
                f"Registered providers: {self.list_providers()}"
            )
        return str(key), provider, entry

    def create(
        self,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        **overrides: Any,
    ) -> Optional[BaseQueryExpander]:
        if enabled is None:
            enabled = self.is_enabled()
        if not enabled:
            return None

        _key, provider, entry = self.resolve(name)
        options = {**entry, **overrides}
        options.pop("provider", None)
        return self._providers[provider](**options)
