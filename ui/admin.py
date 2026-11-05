"""Admin/tenancy safety UX helpers (issue #135)."""

from __future__ import annotations

from typing import Any, Dict, Mapping


def scope_indicator(tenancy: Mapping[str, Any] | None) -> Dict[str, Any]:
    tenancy = tenancy or {}
    enabled = bool(tenancy.get("enabled"))
    default_tenant = tenancy.get("default_tenant") or "default"
    return {
        "enabled": enabled,
        "default_tenant": default_tenant,
        "warning": "Tenant isolation is enabled. Requests are scoped to the resolved tenant." if enabled else "Tenancy is disabled; single-tenant mode.",
        "scope_text": f"Tenant: {default_tenant}" if enabled else "Tenant: (disabled)",
    }


def confirm_action(action: str) -> str:
    return f"Confirm {action}? This is a sensitive administrative action."


def audit_export_rows(events: list) -> list:
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        out.append({
            "timestamp": ev.get("timestamp"),
            "event_type": ev.get("event_type"),
            "action": ev.get("action"),
            "outcome": ev.get("outcome"),
            "request_id": ev.get("request_id"),
            "tenant": ev.get("tenant"),
        })
    return out
