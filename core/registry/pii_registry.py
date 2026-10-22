"""Configuration-driven PII / DLP policy registry (Workstream B3, issue #54).

Reads the ``pii:`` block of the observability config:

    pii:
      enabled: false
      classes: [email, phone, credit_card, national_id, ip_address]
      mode: redact
      mask: "[REDACTED]"
      ner:
        enabled: false
        model: en_core_web_sm
        classes: [person_name, address]

This block governs **scrubbing** - what is stripped from traces, logs, the
config view and the query that is handed to the model. Enforcement at the
input/output edges is configured separately through the ``pii`` guardrail
provider in ``config/guardrails.yaml`` (issue #52 framework).

The registry is the only thing the composition root depends on, so the
detector is swappable by config and no app module imports a concrete
detector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from core.interfaces.pii import DEFAULT_PII_CLASSES, PiiDetector


class PiiRegistry:
    """Resolve the PII scrub policy from configuration."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.config_path = config_path
        if config is not None:
            self.config: Dict[str, Any] = dict(config)
        else:
            self.config = self._load(config_path)
        self._section = self._resolve_section(self.config)

    # -- loading ----------------------------------------------------------

    @staticmethod
    def _load(config_path: Optional[str]) -> Dict[str, Any]:
        if not config_path:
            return {}
        try:
            with open(config_path, "r") as handle:
                loaded = yaml.safe_load(handle) or {}
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _resolve_section(config: Dict[str, Any]) -> Dict[str, Any]:
        section = config.get("pii") if isinstance(config, dict) else None
        return section if isinstance(section, dict) else {}

    # -- policy -----------------------------------------------------------

    def is_enabled(self) -> bool:
        """Whether PII scrubbing is switched on (default: off)."""
        return bool(self._section.get("enabled", False))

    def classes(self) -> List[str]:
        """The PII classes covered by the policy."""
        raw = self._section.get("classes")
        if raw is None:
            return list(DEFAULT_PII_CLASSES)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            return list(DEFAULT_PII_CLASSES)
        selected = [str(item).strip().lower() for item in raw]
        return [item for item in selected if item]

    def mode(self) -> str:
        """``redact`` (default) or ``block``."""
        return str(self._section.get("mode", "redact") or "redact").strip().lower()

    def mask(self) -> Optional[str]:
        """Optional override for the default per-class mask token."""
        mask = self._section.get("mask")
        return str(mask) if mask else None

    def build_detector(
        self,
        classes: Optional[Sequence[str]] = None,
        *,
        force: bool = False,
    ) -> Optional[PiiDetector]:
        """Build the detector for this policy, or ``None`` when disabled.

        ``classes`` overrides the configured class list (the composition root
        unions the guardrail classes in so traces/logs are scrubbed even when
        only the edge guardrail - not the ``pii:`` block - is enabled).
        ``force`` builds a detector regardless of ``enabled`` for that case.
        """
        if not force and not self.is_enabled():
            return None

        selected = self.classes() if classes is None else [
            str(item).strip().lower() for item in classes if str(item).strip()
        ]
        if not selected:
            return None

        from core.implementations.pii_detector import build_pii_detector

        extra_patterns = self._section.get("extra_patterns")
        return build_pii_detector(
            classes=selected,
            national_id_patterns=self._section.get("national_id_patterns"),
            extra_patterns=extra_patterns if isinstance(extra_patterns, dict) else None,
            ner=self._section.get("ner") if isinstance(self._section.get("ner"), dict) else None,
        )

    @classmethod
    def from_config_path(cls, config_path: Optional[str]) -> "PiiRegistry":
        return cls(config_path=config_path)

    @classmethod
    def default_config_path(cls) -> str:
        return str(
            Path(__file__).resolve().parent.parent.parent / "config" / "observability.yaml"
        )

    def describe(self) -> Dict[str, Any]:
        """A redacted summary of the policy (safe for the config view)."""
        return {
            "enabled": self.is_enabled(),
            "classes": self.classes(),
            "mode": self.mode(),
            "mask": self.mask(),
            "ner_enabled": bool(
                isinstance(self._section.get("ner"), dict)
                and self._section["ner"].get("enabled", False)
            ),
        }


def resolve_pii_classes(section: Optional[Dict[str, Any]]) -> List[str]:
    """Helper for callers that hold a raw ``pii:`` section."""
    if not isinstance(section, dict):
        return list(DEFAULT_PII_CLASSES)
    raw: Sequence[Any] = section.get("classes") or DEFAULT_PII_CLASSES
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip().lower() for item in raw if str(item).strip()]
