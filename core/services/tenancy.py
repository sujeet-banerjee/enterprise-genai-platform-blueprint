"""Tenant / workspace model (issue #48, workstream A1).

The platform historically treated every caller as one global installation:
cache, spend history, audit trail and evaluation stores were shared. This module
introduces a first-class *tenant* (optionally scoped to a workspace and app) so
one deployment can serve many teams with isolation and per-tenant policy.

Config (``config/tenants.yaml``)::

    enabled: false                 # opt-in; disabled => implicit default tenant
    default_tenant: default
    tenants:
      acme:
        workspace: acme-prod
        app: support-copilot
        budget_cap_usd: 5.0      # window spend cap enforced per request
        top_k_max: 3             # retrieval depth cap
        allowed_models: [local-qwen]
        overrides:               # tenant overlay on top of global config
          retrieval:
            top_k: 2
    api_keys:                    # optional key -> tenant mapping
      "acme-key": acme

Tenant resolution: explicit ``X-Tenant-ID`` header first, then the API key
mapping, then ``default_tenant``. When disabled the resolver always returns the
implicit default tenant, so existing deployments behave exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_TENANT_ID = "default"


class UnknownTenantError(ValueError):
    """Raised when a request names a tenant that is not configured."""

    def __init__(self, tenant_id: str):
        self.tenant_id = str(tenant_id)
        super().__init__(f"Unknown tenant '{self.tenant_id}'.")


@dataclass(frozen=True)
class Tenant:
    """Resolved tenant identity plus optional per-tenant policy."""

    id: str = DEFAULT_TENANT_ID
    workspace: str = DEFAULT_TENANT_ID
    app: str = DEFAULT_TENANT_ID
    budget_cap_usd: Optional[float] = None
    top_k_max: Optional[int] = None
    allowed_models: Optional[List[str]] = None
    overrides: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workspace": self.workspace,
            "app": self.app,
            "budget_cap_usd": self.budget_cap_usd,
            "top_k_max": self.top_k_max,
            "allowed_models": (
                list(self.allowed_models) if self.allowed_models is not None else None
            ),
            "overrides": dict(self.overrides),
        }


def _merge_overlay(base: Any, overlay: Any) -> Any:
    """Recursively merge ``overlay`` on top of ``base``.

    Dicts are merged key-by-key (overlay wins); any other value replaces the
    base value. The inputs are never mutated.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged: Dict[str, Any] = {str(key): value for key, value in base.items()}
        for key, value in overlay.items():
            key = str(key)
            if key in merged:
                merged[key] = _merge_overlay(merged[key], value)
            else:
                merged[key] = value
        return merged
    return overlay


class TenantResolver:
    """Resolves requests to tenants and answers policy/overlay questions."""

    def __init__(
        self,
        enabled: bool = False,
        default_tenant: str = DEFAULT_TENANT_ID,
        tenants: Optional[Dict[str, Any]] = None,
        api_keys: Optional[Dict[str, str]] = None,
    ):
        self.enabled = bool(enabled)
        self.default_tenant = str(default_tenant or DEFAULT_TENANT_ID)
        self.tenants: Dict[str, Tenant] = {
            str(tenant_id): self._normalize_tenant(str(tenant_id), cfg)
            for tenant_id, cfg in (tenants or {}).items()
        }
        self.api_keys: Dict[str, str] = {
            str(key): str(tenant_id)
            for key, tenant_id in (api_keys or {}).items()
        }

    # -- construction -----------------------------------------------------

    @staticmethod
    def _normalize_tenant(tenant_id: str, cfg: Any) -> Tenant:
        cfg = cfg if isinstance(cfg, dict) else {}
        budget = cfg.get("budget_cap_usd")
        top_k_max = cfg.get("top_k_max")
        allowed_models = cfg.get("allowed_models")
        overrides = cfg.get("overrides")
        return Tenant(
            id=tenant_id,
            workspace=str(cfg.get("workspace") or tenant_id),
            app=str(cfg.get("app") or tenant_id),
            budget_cap_usd=float(budget) if isinstance(budget, (int, float)) else None,
            top_k_max=int(top_k_max) if isinstance(top_k_max, int) else None,
            allowed_models=(
                [str(model) for model in allowed_models]
                if isinstance(allowed_models, list)
                else None
            ),
            overrides=dict(overrides) if isinstance(overrides, dict) else {},
        )

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "TenantResolver":
        config = config or {}
        return cls(
            enabled=bool(config.get("enabled", False)),
            default_tenant=str(config.get("default_tenant") or DEFAULT_TENANT_ID),
            tenants=config.get("tenants"),
            api_keys=config.get("api_keys"),
        )

    # -- resolution -------------------------------------------------------

    def _implicit_default(self) -> Tenant:
        configured = self.tenants.get(self.default_tenant)
        if configured is not None:
            return configured
        return Tenant(id=self.default_tenant)

    def resolve(
        self,
        tenant_header: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Tenant:
        """Resolve a request to a tenant.

        Disabled resolver => implicit default tenant (feature is opt-in).
        Header wins over the API-key mapping; an unknown explicit tenant is an
        error rather than a silent fallback (never leak tenant-spoofed data).
        """
        if not self.enabled:
            return self._implicit_default()

        header = str(tenant_header).strip() if tenant_header else ""
        if header:
            tenant = self.tenants.get(header)
            if tenant is None:
                raise UnknownTenantError(header)
            return tenant

        if api_key and api_key in self.api_keys:
            mapped = self.api_keys[api_key]
            tenant = self.tenants.get(mapped)
            if tenant is None:
                raise UnknownTenantError(mapped)
            return tenant

        return self._implicit_default()

    def is_known(self, tenant_id: str) -> bool:
        return str(tenant_id) in self.tenants

    def get(self, tenant_id: str) -> Optional[Tenant]:
        return self.tenants.get(str(tenant_id))

    def tenant_ids(self) -> List[str]:
        return sorted(self.tenants)

    def overlay(self, tenant_id: str, section: str) -> Dict[str, Any]:
        """Return the tenant's override mapping for one config section."""
        tenant = self.tenants.get(str(tenant_id))
        if tenant is None:
            return {}
        section_overlay = tenant.overrides.get(section)
        return dict(section_overlay) if isinstance(section_overlay, dict) else {}

    def apply_overlay(
        self, section: str, values: Dict[str, Any], tenant_id: str
    ) -> Dict[str, Any]:
        """Merge a tenant's overlay for ``section`` on top of global values."""
        overlay = self.overlay(tenant_id, section)
        if not overlay:
            return dict(values or {})
        merged = _merge_overlay(values or {}, overlay)
        return merged if isinstance(merged, dict) else dict(values or {})

    def describe(self, tenant_id: str) -> Dict[str, Any]:
        tenant = self.tenants.get(str(tenant_id)) or Tenant(id=str(tenant_id))
        return tenant.as_dict()

    def describe_all(self) -> List[Dict[str, Any]]:
        return [self.tenants[tenant_id].as_dict() for tenant_id in self.tenant_ids()]

    def tenants_for_api_key(self, api_key: Optional[str]) -> Iterable[str]:
        """Tenant ids reachable with ``api_key`` (all when unmapped/disabled)."""
        if not self.enabled:
            return []
        if api_key and api_key in self.api_keys:
            return [self.api_keys[api_key]]
        return []
