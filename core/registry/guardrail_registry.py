"""Configuration-driven guardrail registry and factory (Workstream B1, #52).

Mirrors ``RerankerRegistry`` / ``EvaluatorRegistry``. Reads a dedicated
``config/guardrails.yaml``:

    enabled: false
    input:
      - provider: deny_list
        terms: ["ignore previous instructions"]
        mask: "[REDACTED]"
    output:
      - provider: schema_validator
        expect_json: true
        required_keys: ["answer"]

``input`` and ``output`` are **ordered** lists: guardrails run in the configured
order and a block stops the chain. Each entry's ``provider`` selects a factory;
the remaining keys are the guardrail's options.

The registry is the *only* thing the composition root depends on, so backends
swap by config and ``app/main.py`` never imports a concrete guardrail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from core.interfaces.guardrail import BaseGuardrail


class GuardrailRegistry:
    """Resolve ordered input/output guardrail chains from configuration."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "guardrails.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        self.config = self._load(config_path)

        self._providers: Dict[str, Callable[..., BaseGuardrail]] = {}
        self._register_default_providers()

    @staticmethod
    def _load(config_path: Optional[str]) -> dict:
        if not config_path:
            return {}
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _register_default_providers(self) -> None:
        self.register("noop", self._build_noop)
        self.register("deny_list", self._build_deny_list)
        self.register("schema_validator", self._build_schema_validator)
        self.register("injection", self._build_injection)

    @staticmethod
    def _build_noop(**_options: Any) -> BaseGuardrail:
        from core.implementations.guardrails import NoopGuardrail

        return NoopGuardrail()

    @staticmethod
    def _build_deny_list(**options: Any) -> BaseGuardrail:
        from core.implementations.guardrails import DenyListGuardrail

        return DenyListGuardrail(
            terms=options.get("terms"),
            regex=bool(options.get("regex", False)),
            mask=options.get("mask"),
            case_insensitive=bool(options.get("case_insensitive", True)),
            reason=options.get("reason"),
        )

    @staticmethod
    def _build_schema_validator(**options: Any) -> BaseGuardrail:
        from core.implementations.guardrails import SchemaValidatorGuardrail

        return SchemaValidatorGuardrail(
            required_keys=options.get("required_keys"),
            forbidden_keys=options.get("forbidden_keys"),
            expect_json=bool(options.get("expect_json", False)),
            reason=options.get("reason"),
        )

    @staticmethod
    def _build_injection(**options: Any) -> BaseGuardrail:
        from core.implementations.injection_guardrail import (
            InjectionGuardrail,
            build_injection_classifier,
        )

        classifier_kind = options.get("classifier")
        classifier_factory = None
        if classifier_kind not in (None, "none", "", "off"):
            kind = classifier_kind
            classifier_options = dict(options.get("classifier_options") or {})

            def classifier_factory(_kind=kind, _opts=classifier_options):
                built = build_injection_classifier(_kind, **_opts)
                assert built is not None  # validated above
                return built

        return InjectionGuardrail(
            sensitivity=str(options.get("sensitivity", "medium")),
            trust_retrieved_documents=bool(
                options.get("trust_retrieved_documents", False)
            ),
            classifier_factory=classifier_factory,
            neutralize_mode=str(options.get("neutralize_mode", "delimit")),
            mask=str(options.get("mask", "[REDACTED-INSTRUCTION]")),
        )

    def register(self, provider_name: str, factory: Callable[..., BaseGuardrail]) -> None:
        """Register a guardrail provider factory (plug-in seam)."""
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def _build_chain(self, section: str) -> List[BaseGuardrail]:
        entries = self.config.get(section) or []
        if not isinstance(entries, list):
            return []

        chain: List[BaseGuardrail] = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {"provider": entry}
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider", "")).lower()
            if provider not in self._providers:
                raise ValueError(
                    f"Unknown guardrail provider: '{provider}'. "
                    f"Registered providers: {self.list_providers()}"
                )
            options = {k: v for k, v in entry.items() if k != "provider"}
            guardrail = self._providers[provider](**options)
            # Per-entry stage override wins over the class default.
            explicit_stage = entry.get("stage")
            if explicit_stage:
                guardrail.stage = str(explicit_stage)
            elif getattr(guardrail, "stage", None) is None:
                guardrail.stage = section
            chain.append(guardrail)
        return chain

    def build_input_chain(self) -> List[BaseGuardrail]:
        if not self.is_enabled():
            return []
        return self._build_chain("input")

    def build_output_chain(self) -> List[BaseGuardrail]:
        if not self.is_enabled():
            return []
        return self._build_chain("output")
