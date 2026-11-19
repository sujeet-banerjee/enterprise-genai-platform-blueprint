"""Pure view-model helpers for the branded console shell (issue #240).

No Streamlit or backend imports: the header/scope contract stays testable and
the HTTP-only UI rule remains intact.
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping
from urllib.parse import urlsplit

from ui.navigation import role_label

PRODUCT_NAME = "Enterprise GenAI Platform Console"
PAGE_TITLE = "Enterprise GenAI Platform Console"
PAGE_ICON = ":material/space_dashboard:"
SIDEBAR_MARK = "GENAI"
DEFAULT_SCREEN = "Overview / Health"

_HEALTHY_READY = {"ready", "ok", "healthy", "healthy_ok"}
_UNHEALTHY_READY = {"not_ready", "not ready", "degraded", "error", "failed"}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _ok(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value.get("ok"))
    return bool(getattr(value, "ok", False))


def _status_code(value: Any) -> int:
    raw = value.get("status_code") if isinstance(value, Mapping) else getattr(value, "status_code", 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _data(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return _as_mapping(value.get("data"))
    return _as_mapping(getattr(value, "data", None))


def environment_label(api_base_url: str = "", demo_mode: bool = False) -> str:
    """Compact environment chip derived from the configured API base URL."""
    if demo_mode:
        return "demo"
    host = (urlsplit(str(api_base_url or "")).hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return "local"
    return host[:32]


def health_view(health: Any, ready: Any) -> dict:
    """Combine /health and /ready into one status dot view-model."""
    health_status = str(_data(health).get("status") or "")
    ready_status = str(_data(ready).get("status") or "")
    health_ok = _ok(health) or _status_code(health) in (200, 201, 204)
    ready_ok = _ok(ready) or _status_code(ready) in (200, 201, 204)
    normalized = ready_status.strip().lower().replace(" ", "_")
    detail = f"health: {health_status or '-'}; ready: {ready_status or '-'}"

    if health_ok and ready_ok and normalized not in _UNHEALTHY_READY:
        return {
            "state": "ready",
            "tone": "success",
            "label": "ready",
            "detail": detail,
            "health_ok": True,
            "ready_ok": True,
        }
    if health_ok and ready_ok:
        return {
            "state": "degraded",
            "tone": "warning",
            "label": "not ready",
            "detail": detail,
            "health_ok": True,
            "ready_ok": True,
        }
    if health_ok:
        return {
            "state": "starting",
            "tone": "warning",
            "label": "not ready",
            "detail": detail,
            "health_ok": True,
            "ready_ok": False,
        }
    if ready_ok:
        return {
            "state": "degraded",
            "tone": "warning",
            "label": "health check failed",
            "detail": detail,
            "health_ok": False,
            "ready_ok": True,
        }
    return {
        "state": "offline",
        "tone": "danger",
        "label": "unavailable",
        "detail": detail,
        "health_ok": False,
        "ready_ok": False,
    }


def scope_view(access: Any, environment: str = "local") -> dict:
    """Normalize access/tenant data into the header scope chips."""
    context = _as_mapping(access)
    tenant = _as_mapping(context.get("tenant"))
    tenant_id = str(tenant.get("id") or tenant.get("tenant") or "default")
    workspace = str(tenant.get("workspace") or "default")
    role = str(context.get("role") or "admin")
    enabled = bool(context.get("enabled"))
    return {
        "environment": environment or "local",
        "tenant": tenant_id,
        "workspace": workspace,
        "scope": f"{tenant_id} / {workspace}",
        "role": role_label(role),
        "rbac": "RBAC on" if enabled else "RBAC off",
    }


def header_view(
    screen_title: str,
    access: Any,
    health: Any,
    ready: Any,
    environment: str = "local",
    demo_mode: bool = False,
) -> dict:
    """Build the complete branded header view-model for one render."""
    return {
        "product": PRODUCT_NAME,
        "screen_title": str(screen_title or DEFAULT_SCREEN),
        "scope": scope_view(access, environment),
        "health": health_view(health, ready),
        "demo": bool(demo_mode),
    }


def header_markdown(view: Mapping[str, Any]) -> str:
    """Render the header as escaped HTML for Streamlit markdown."""
    data = _as_mapping(view)
    scope = _as_mapping(data.get("scope"))
    status = _as_mapping(data.get("health"))
    product = escape(str(data.get("product") or PRODUCT_NAME), quote=True)
    screen = escape(str(data.get("screen_title") or DEFAULT_SCREEN), quote=True)
    environment = escape(str(scope.get("environment") or "local"), quote=True)
    role = escape(str(scope.get("role") or "admin"), quote=True)
    rbac = escape(str(scope.get("rbac") or "RBAC off"), quote=True)
    tenant = escape(str(scope.get("scope") or "default / default"), quote=True)
    tone = escape(str(status.get("tone") or "danger"), quote=True)
    label = escape(str(status.get("label") or "unavailable"), quote=True)
    detail = escape(str(status.get("detail") or ""), quote=True)
    demo_chip = (
        '<span class="genai-chip genai-chip-warning">demo data</span>'
        if data.get("demo")
        else ""
    )
    return (
        '<div class="genai-app-header" role="banner">'
        '<div class="genai-header-identity">'
        f'<span class="genai-header-mark" aria-hidden="true">{SIDEBAR_MARK}</span>'
        '<span class="genai-header-titles">'
        f'<span class="genai-product-title">{product}</span>'
        f'<span class="genai-screen-title">{screen}</span>'
        "</span></div>"
        '<div class="genai-header-chips">'
        f'<span class="genai-chip genai-chip-neutral" title="Environment">{environment}</span>'
        f'<span class="genai-chip genai-chip-neutral" title="Tenant / workspace">{tenant}</span>'
        f'<span class="genai-chip genai-chip-neutral" title="Access role">{role} - {rbac}</span>'
        f'{demo_chip}'
        f'<span class="genai-chip genai-chip-{tone}" title="{detail}">'
        f'<span class="genai-health-dot genai-dot-{tone}" aria-hidden="true"></span>{label}</span>'
        "</div></div>"
    )


def sidebar_brand_markdown() -> str:
    """Static sidebar text mark; no image asset or external icon dependency."""
    return (
        '<div class="genai-sidebar-brand">'
        f'<span class="genai-sidebar-mark">{escape(SIDEBAR_MARK, quote=True)}</span>'
        f'<span class="genai-sidebar-name">{escape(PRODUCT_NAME, quote=True)}</span>'
        "</div>"
    )
