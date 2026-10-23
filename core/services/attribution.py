"""Request attribution context (issue #50, workstream A3).

Every trace, metric, audit event and cost record needs the *who/which team /
which app* dimensions so spend can be reported without rebuilding it from logs.
The context is resolved once at ingress (identity + tenancy) and read by the
pipeline, history, audit trail and metrics collector.

The feature is opt-in: with attribution disabled only the tenancy dimensions
(tenant/workspace/app) are populated and ``user``/``cost_center`` collapse to
``default``. Whatever the mode, the dimensions are always *present* so a
dashboard never has to special-case their absence.
"""

from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

DEFAULT_DIMENSION = "default"
_MAX_IDENTIFIER_LENGTH = 64
_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9@._:+-]+")


def safe_identifier(value: Any, fallback: str = DEFAULT_DIMENSION) -> str:
    """Normalise a free-text identity to a bounded, label-safe token.

    Attribution values end up in Prometheus labels, trace payloads and audit
    files, so arbitrary caller-supplied text must never be echoed verbatim:
    whitespace/control characters and anything outside a conservative charset
    are replaced, and the result is capped at 64 characters. An empty value
    becomes ``default``.
    """
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    text = _SAFE_IDENTIFIER.sub("-", text).strip("-")
    if not text:
        return fallback
    return text[:_MAX_IDENTIFIER_LENGTH]


@dataclass(frozen=True)
class AttributionContext:
    """Request-scoped attribution dimensions."""

    tenant: str = DEFAULT_DIMENSION
    workspace: str = DEFAULT_DIMENSION
    app: str = DEFAULT_DIMENSION
    user: str = DEFAULT_DIMENSION
    cost_center: str = DEFAULT_DIMENSION

    @classmethod
    def from_values(
        cls,
        tenant: Optional[str] = None,
        workspace: Optional[str] = None,
        app: Optional[str] = None,
        user: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> "AttributionContext":
        return cls(
            tenant=safe_identifier(tenant),
            workspace=safe_identifier(workspace),
            app=safe_identifier(app),
            user=safe_identifier(user),
            cost_center=safe_identifier(cost_center),
        )

    def merged(
        self,
        tenant: Optional[str] = None,
        workspace: Optional[str] = None,
        app: Optional[str] = None,
        user: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> "AttributionContext":
        """Return a copy with explicit non-None values overriding this one."""
        updates: Dict[str, str] = {}
        for key, value in (
            ("tenant", tenant),
            ("workspace", workspace),
            ("app", app),
            ("user", user),
            ("cost_center", cost_center),
        ):
            if value is not None:
                updates[key] = safe_identifier(value)
        return replace(self, **updates) if updates else self

    def dimensions(self) -> Dict[str, str]:
        return {
            "tenant": self.tenant,
            "workspace": self.workspace,
            "app": self.app,
            "user": self.user,
            "cost_center": self.cost_center,
        }

    def labels(self) -> Dict[str, str]:
        """The subset used as metric labels (keeps cardinality bounded)."""
        return {
            "tenant": self.tenant,
            "workspace": self.workspace,
            "app": self.app,
            "user": self.user,
        }


@dataclass(frozen=True)
class AttributionSettings:
    """Config-driven switches for optional dimensions (``config/attribution.yaml``)."""

    enabled: bool = False
    include_user: bool = True
    include_cost_center: bool = True
    default_dimension: str = DEFAULT_DIMENSION

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "AttributionSettings":
        config = config or {}
        section = config.get("attribution", config)
        if not isinstance(section, dict):
            section = {}
        return cls(
            enabled=bool(section.get("enabled", False)),
            include_user=bool(section.get("include_user", True)),
            include_cost_center=bool(section.get("include_cost_center", True)),
            default_dimension=safe_identifier(
                section.get("default_dimension"), DEFAULT_DIMENSION
            ),
        )

    def build(
        self,
        tenant: Optional[str] = None,
        workspace: Optional[str] = None,
        app: Optional[str] = None,
        user: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> AttributionContext:
        """Build the request context, honouring the opt-in switches."""
        fallback = self.default_dimension
        return AttributionContext(
            tenant=safe_identifier(tenant, fallback),
            workspace=safe_identifier(workspace, fallback),
            app=safe_identifier(app, fallback),
            user=safe_identifier(
                user if self.enabled and self.include_user else None, fallback
            ),
            cost_center=safe_identifier(
                cost_center if self.enabled and self.include_cost_center else None,
                fallback,
            ),
        )


_CURRENT: contextvars.ContextVar[Optional[AttributionContext]] = contextvars.ContextVar(
    "genai_attribution", default=None
)


def set_attribution(
    context: AttributionContext,
) -> "contextvars.Token[Optional[AttributionContext]]":
    return _CURRENT.set(context)


def reset_attribution(token: "contextvars.Token[Optional[AttributionContext]]") -> None:
    try:
        _CURRENT.reset(token)
    except ValueError:  # pragma: no cover - token from another context
        _CURRENT.set(None)


def current_attribution() -> Optional[AttributionContext]:
    return _CURRENT.get()


def ensure_attribution(
    tenant: Optional[str] = None,
    workspace: Optional[str] = None,
    app: Optional[str] = None,
    user: Optional[str] = None,
    cost_center: Optional[str] = None,
) -> AttributionContext:
    """Return the current context (merged with overrides) or build a default."""
    base = _CURRENT.get() or AttributionContext()
    return base.merged(
        tenant=tenant,
        workspace=workspace,
        app=app,
        user=user,
        cost_center=cost_center,
    )
