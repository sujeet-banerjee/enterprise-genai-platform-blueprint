"""Lightweight, config-driven RBAC / persona layer (issue #29).

The platform previously had a single global API-key stub and no authorization.
This module adds a small role model: an API key maps to a *role*, and each role
carries a set of *capabilities* plus optional request caps (``top_k_max``) and
model allow-lists. It is deliberately dependency-free and off by default.

Config (``config/access_control.yaml``)::

    enabled: false
    default_role: admin
    roles:
      admin:
        capabilities: ["query", "batch", "rebuild", "audit", ...]
      analyst:
        capabilities: ["query", "batch", "evaluate"]
        top_k_max: 5
        allowed_models: ["local-qwen"]
    api_keys:
      "analyst-key": analyst

When ``enabled`` is false the controller is inert: every caller resolves to the
default role with all capabilities, so existing deployments are unaffected.
"""

from typing import Any, Dict, List, Optional, Sequence

CAPABILITY_QUERY = "query"
CAPABILITY_BATCH = "batch"
CAPABILITY_EVALUATE = "evaluate"
CAPABILITY_EXPERIMENT = "experiment"
CAPABILITY_REBUILD = "rebuild"
CAPABILITY_INTROSPECT = "introspect"
CAPABILITY_GOVERNANCE = "governance"
CAPABILITY_AUDIT = "audit"

ALL_CAPABILITIES: Sequence[str] = (
    CAPABILITY_QUERY,
    CAPABILITY_BATCH,
    CAPABILITY_EVALUATE,
    CAPABILITY_EXPERIMENT,
    CAPABILITY_REBUILD,
    CAPABILITY_INTROSPECT,
    CAPABILITY_GOVERNANCE,
    CAPABILITY_AUDIT,
)


class AccessController:
    """Resolves API keys to roles and answers capability/cap questions."""

    def __init__(
        self,
        enabled: bool = True,
        roles: Optional[Dict[str, Any]] = None,
        api_keys: Optional[Dict[str, str]] = None,
        default_role: str = "admin",
    ):
        self.enabled = bool(enabled)
        self.roles: Dict[str, Dict[str, Any]] = {
            str(name): self._normalize_role(cfg)
            for name, cfg in (roles or {}).items()
        }
        self.api_keys: Dict[str, str] = {
            str(key): str(role) for key, role in (api_keys or {}).items()
        }
        self.default_role = str(default_role)

    @staticmethod
    def _normalize_role(cfg: Any) -> Dict[str, Any]:
        cfg = cfg if isinstance(cfg, dict) else {}
        capabilities = cfg.get("capabilities")
        if not isinstance(capabilities, list):
            capabilities = []
        top_k_max = cfg.get("top_k_max")
        allowed_models = cfg.get("allowed_models")
        return {
            "capabilities": [str(c) for c in capabilities],
            "top_k_max": int(top_k_max) if isinstance(top_k_max, int) else None,
            "allowed_models": (
                [str(m) for m in allowed_models]
                if isinstance(allowed_models, list)
                else None
            ),
        }

    # -- resolution -------------------------------------------------------

    def resolve_role(self, api_key: Optional[str]) -> str:
        """Return the role for an API key.

        Disabled controller => default role (which carries all capabilities).
        When enabled, an unknown/absent key maps to ``default_role`` unless a
        matching key is configured.
        """
        if not self.enabled:
            return self.default_role
        if api_key is not None and api_key in self.api_keys:
            return self.api_keys[api_key]
        return self.default_role

    # -- authorization ----------------------------------------------------

    def capabilities(self, role: str) -> List[str]:
        if not self.enabled:
            return list(ALL_CAPABILITIES)
        return list(self.roles.get(role, {}).get("capabilities") or [])

    def has_capability(self, role: str, capability: str) -> bool:
        if not self.enabled:
            return True
        return capability in self.capabilities(role)

    def top_k_max(self, role: str) -> Optional[int]:
        if not self.enabled:
            return None
        return self.roles.get(role, {}).get("top_k_max")

    def allowed_models(self, role: str) -> Optional[List[str]]:
        if not self.enabled:
            return None
        return self.roles.get(role, {}).get("allowed_models")

    def describe(self, role: str) -> Dict[str, Any]:
        return {
            "role": role,
            "capabilities": self.capabilities(role),
            "top_k_max": self.top_k_max(role),
            "allowed_models": self.allowed_models(role),
        }

    # -- config -----------------------------------------------------------

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "AccessController":
        config = config or {}
        return cls(
            enabled=bool(config.get("enabled", False)),
            roles=config.get("roles"),
            api_keys=config.get("api_keys"),
            default_role=str(config.get("default_role", "admin")),
        )
