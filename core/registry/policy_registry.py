"""Registry for policy engines (#121)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import yaml

from core.interfaces.policy import BasePolicyEngine, NoopPolicyEngine


class PolicyRegistry:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent.parent.parent / "config" / "policies.yaml")
        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}
        self._providers: Dict[str, type[BasePolicyEngine]] = {}
        self.register("noop", NoopPolicyEngine)

    def register(self, name: str, provider: type[BasePolicyEngine]) -> None:
        self._providers[str(name).lower()] = provider

    def list_providers(self):
        return sorted(self._providers.keys())

    def create(self, name: Optional[str] = None) -> BasePolicyEngine:
        cfg = self.config.get("policies") or self.config
        if not cfg.get("enabled", False):
            return NoopPolicyEngine()
        engine = str(name or cfg.get("engine") or "noop").lower()
        cls = self._providers.get(engine)
        if cls is None:
            return NoopPolicyEngine()
        return cls()
