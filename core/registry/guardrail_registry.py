"""Configuration-driven guardrail registry and factory (Workstream B1, #52).

Mirrors ``RerankerRegistry`` / ``EvaluatorRegistry``. Reads a dedicated
``config/guardrails.yaml``:

    enabled: false
    profile: standard
    profiles:
      standard:
        input:
          - provider: injection
            sensitivity: medium
        output:
          - provider: deny_list
            terms: ["ignore previous instructions"]
            mask: "[REDACTED-POLICY]"
    input: []
    output: []

``input`` and ``output`` are **ordered** lists: guardrails run in the configured
order and a block stops the chain. Each entry's ``provider`` selects a factory;
the remaining keys are the guardrail's options.

``profile`` names an adoptable preset declared under ``profiles`` (issue #88).
A section with an explicit, **non-empty** entry list replaces the profile chain
for that edge; an absent/empty section inherits the profile's chain. The feature
stays disabled until ``enabled: true``.

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

    #: Sentinel profile meaning "no preset" (explicit chains only).
    NO_PROFILE = "none"

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "guardrails.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        self.config = self._load(config_path)
        self.profile_name = self._resolve_profile_name()
        self._profiles = self._load_profiles()

        self._providers: Dict[str, Callable[..., BaseGuardrail]] = {}
        self._register_default_providers()

    def _resolve_profile_name(self) -> str:
        raw = self.config.get("profile")
        name = str(raw).strip().lower() if raw else ""
        return name or self.NO_PROFILE

    def _load_profiles(self) -> Dict[str, Any]:
        raw = self.config.get("profiles")
        profiles = (
            {str(key).strip().lower(): value for key, value in raw.items()}
            if isinstance(raw, dict)
            else {}
        )
        if self.profile_name != self.NO_PROFILE and self.profile_name not in profiles:
            raise ValueError(
                f"Unknown guardrail profile: '{self.profile_name}'. "
                f"Defined profiles: {sorted(profiles) or 'none'}"
            )
        return profiles

    def _section_entries(self, section: str) -> list:
        """Explicit entries for ``section``, else the selected profile's chain."""
        explicit = self.config.get(section)
        if isinstance(explicit, list) and explicit:
            return explicit
        profile = self._profiles.get(self.profile_name)
        if not isinstance(profile, dict):
            return []
        entries = profile.get(section)
        return entries if isinstance(entries, list) else []

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
        self.register("pii", self._build_pii)

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

    @staticmethod
    def _build_pii(**options: Any) -> BaseGuardrail:
        from core.implementations.pii_detector import build_pii_detector
        from core.implementations.pii_guardrail import PiiGuardrail

        classes = options.get("classes")
        detector = build_pii_detector(
            classes=classes,
            national_id_patterns=options.get("national_id_patterns"),
            extra_patterns=options.get("extra_patterns"),
            ner=options.get("ner"),
        )

        return PiiGuardrail(
            classes=classes,
            mode=str(options.get("mode", "redact")),
            mask=options.get("mask"),
            detector=detector,
            reason=options.get("reason"),
        )

    def register(self, provider_name: str, factory: Callable[..., BaseGuardrail]) -> None:
        """Register a guardrail provider factory (plug-in seam)."""
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def describe(self) -> Dict[str, Any]:
        """Resolved chains for introspection (issue #86).

        The chains are reported whether or not the master toggle is on, so an
        operator can preview what enabling the feature would run; ``enabled``
        says whether they are currently active. Errors are collected per
        section instead of raising, so a bad entry in a disabled config cannot
        turn a read-only endpoint into a 500.
        """
        result: Dict[str, Any] = {
            "enabled": self.is_enabled(),
            "profile": self.profile_name,
            "providers": self.list_providers(),
            "input": [],
            "output": [],
            "errors": [],
        }
        for section in ("input", "output"):
            try:
                result[section] = [g.describe() for g in self._build_chain(section)]
            except Exception as exc:  # pragma: no cover - defensive
                result["errors"].append(f"{section}: {exc}")
        return result

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def _build_chain(self, section: str) -> List[BaseGuardrail]:
        entries = self._section_entries(section)
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
