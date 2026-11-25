"""Structured Admin presentation helpers (issue #252).

Pure view models for the console's Admin screen. No Streamlit or backend
imports; values are escaped and sensitive keys are masked.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ui.admin import audit_export_rows, confirm_action, scope_indicator
from ui.components import (
    alert_markdown,
    alert_model,
    badge_markdown,
    badge_model,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    redact_payload,
    section_card_markdown,
    section_card_model,
)

_MAX_TEXT = 120


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _short(value: Any, limit: int = _MAX_TEXT) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _list(value: Any, limit: int = 80) -> List[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [item for item in (_short(entry, limit) for entry in value) if item]


def _count_text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return _short(value)


def tenant_cards(data: Any) -> List[Dict[str, Any]]:
    """Resolve tenants into status-labelled cards with curated policy details."""
    payload = _mapping(data)
    enabled = bool(payload.get("enabled"))
    cards: List[Dict[str, Any]] = []
    for raw in payload.get("tenants") or []:
        tenant = _mapping(raw)
        if not tenant:
            continue
        tenant_id = _short(tenant.get("id") or tenant.get("tenant")) or "default"
        workspace = _short(tenant.get("workspace")) or "default"
        app = _short(tenant.get("app")) or "default"
        models = _list(tenant.get("allowed_models"))
        top_k = tenant.get("top_k_max")
        budget = tenant.get("budget_cap_usd")
        guarded = (
            bool(models)
            or (not isinstance(top_k, bool) and isinstance(top_k, int))
            or (not isinstance(budget, bool) and isinstance(budget, (int, float)))
        )
        status = "Implicit" if not enabled else ("Guarded" if guarded else "Configured")
        tone = "warning" if not enabled else ("success" if guarded else "neutral")
        cards.append(
            {
                "id": tenant_id,
                "workspace": workspace,
                "app": app,
                "status": status,
                "badge": badge_model(tone, status),
                "details": {
                    "workspace": workspace,
                    "app": app,
                    "cost_center": _short(tenant.get("cost_center")) or "-",
                    "budget_cap_usd": _count_text(budget),
                    "top_k_max": _count_text(top_k),
                    "allowed_models": ", ".join(models) or "All configured models",
                },
            }
        )
    return cards


def tenant_cards_markdown(cards: Iterable[Mapping[str, Any]]) -> str:
    """Render tenant cards with semantic badges and no raw payload dump."""
    sections: List[str] = []
    for card in cards or []:
        badge = card.get("badge")
        badge_html = badge_markdown(badge) if isinstance(badge, Mapping) else ""
        tenancy_id = escape(_short(card.get("id")) or "tenant")
        details = key_value_markdown(key_value_rows(card.get("details") or {}, redact=False))
        sections.append(
            '<section class="genai-card genai-admin-card">'
            f'<div class="genai-admin-card-head"><h4>{tenancy_id}</h4>{badge_html}</div>'
            f"{details}</section>"
        )
    if not sections:
        return '<div class="genai-card genai-muted">No tenants returned.</div>'
    return f'<div class="genai-admin-cards">{"".join(sections)}</div>'


def user_rows(data: Any) -> List[Dict[str, Any]]:
    """Resolve SCIM users into table rows with explicit status."""
    payload = _mapping(data)
    directory_enabled = bool(payload.get("enabled"))
    rows: List[Dict[str, Any]] = []
    for raw in payload.get("users") or []:
        user = _mapping(raw)
        if not user:
            continue
        user_id = _short(user.get("id") or user.get("userName")) or "-"
        name = _short(user.get("userName")) or user_id
        active = user.get("active", True)
        is_active = bool(active) if isinstance(active, bool) else _text(active).lower() in {
            "active",
            "enabled",
            "true",
        }
        status = "Active" if is_active else "Disabled"
        rows.append(
            {
                "id": user_id,
                "name": name,
                "role": _short(user.get("role")) or "-",
                "groups": _list(user.get("groups")),
                "status": status,
                "badge": badge_model("success" if is_active else "danger", status),
                "source": "SCIM directory" if directory_enabled else "Directory disabled",
            }
        )
    return rows


def user_table_markdown(rows: Iterable[Mapping[str, Any]]) -> str:
    """Render the identity directory as a structured status table."""
    body: List[str] = []
    for row in rows or []:
        badge = row.get("badge")
        badge_html = badge_markdown(badge) if isinstance(badge, Mapping) else ""
        name = escape(_short(row.get("name")) or "-")
        user_id = escape(_short(row.get("id")) or "-")
        role = escape(_short(row.get("role")) or "-")
        groups = escape(", ".join(_list(row.get("groups"))) or "-")
        body.append(
            "<tr>"
            f'<td><span class="genai-admin-user">{name}</span><br><code>{user_id}</code></td>'
            f"<td>{role}</td><td>{groups}</td>"
            f'<td class="genai-admin-status">{badge_html}</td>'
            "</tr>"
        )
    if not body:
        return '<div class="genai-card genai-muted">No users returned or identity disabled.</div>'
    header = (
        '<table class="genai-admin-table"><thead><tr><th>User</th><th>Role</th>'
        "<th>Groups</th><th>Status</th></tr></thead><tbody>"
    )
    return f'{header}{"".join(body)}</tbody></table>'


def recent_audit_rows(data: Any) -> List[Dict[str, Any]]:
    """Extract recent audit events with outcome badges for structured display."""
    payload = _mapping(data)
    rows = audit_export_rows(payload.get("events") or [])
    for row in rows:
        outcome = _short(row.get("outcome")) or "unknown"
        row["badge"] = badge_model(outcome, outcome)
    return rows


def audit_table_markdown(rows: Iterable[Mapping[str, Any]]) -> str:
    """Render recent audit events as a correlated, escaped table."""
    body: List[str] = []
    for row in rows or []:
        badge = row.get("badge")
        badge_html = badge_markdown(badge) if isinstance(badge, Mapping) else ""
        values = [
            escape(_short(redact_payload(row.get("timestamp"))) or "-"),
            escape(_short(redact_payload(row.get("event_type"))) or "-"),
            escape(_short(redact_payload(row.get("action"))) or "-"),
            badge_html,
            escape(_short(redact_payload(row.get("request_id"))) or "-"),
            escape(_short(redact_payload(row.get("tenant"))) or "-"),
        ]
        body.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    if not body:
        return '<div class="genai-card genai-muted">No recent audit events.</div>'
    header = (
        '<div class="genai-audit-timeline"><table class="genai-admin-table">'
        "<thead><tr><th>When</th><th>Event</th><th>Action</th><th>Outcome</th>"
        "<th>Request</th><th>Tenant</th></tr></thead><tbody>"
    )
    return f'{header}{"".join(body)}</tbody></table></div>'


def admin_banners(tenants_data: Any, users_data: Any) -> List[Dict[str, Any]]:
    """Build scope, change-control, and identity banners for sensitive actions."""
    tenants_payload = _mapping(tenants_data)
    cards = tenant_cards(tenants_payload)
    default_tenant = cards[0]["id"] if cards else "default"
    scope = scope_indicator(
        {"enabled": bool(tenants_payload.get("enabled")), "default_tenant": default_tenant}
    )
    alerts = [
        alert_model(
            "Tenant scope",
            scope["warning"],
            tone="warning" if scope["enabled"] else "info",
            hint=scope["scope_text"],
        ),
        alert_model(
            "Change control",
            confirm_action("update tenant configuration"),
            tone="warning",
            hint="Review the tenant and budget before submitting; confirmation is required.",
        ),
    ]
    if not bool(_mapping(users_data).get("enabled")):
        alerts.append(
            alert_model(
                "Identity directory",
                "Identity is disabled; the user list may be empty in single-tenant mode.",
                tone="info",
            )
        )
    return alerts


def banners_markdown(alerts: Iterable[Mapping[str, Any]]) -> str:
    """Render administrative banners as structured alerts."""
    return "".join(alert_markdown(alert) for alert in alerts or [])


def section_cards(
    tenants_html: Any,
    users_html: Any,
    audit_html: Any,
    change_html: Any,
) -> List[Dict[str, Any]]:
    """Build segmented Admin sections from curated markdown fragments."""
    return [
        section_card_model(
            "Tenants",
            "Resolved tenants and per-tenant policy limits.",
            tenants_html,
            actions=["Tenant updates require explicit confirmation"],
        ),
        section_card_model(
            "Users (identity directory)",
            "SCIM users visible to this caller.",
            users_html,
        ),
        section_card_model(
            "Recent audit",
            "Latest events with request correlation.",
            audit_html,
            actions=["Metadata-only CSV export"],
        ),
        section_card_model(
            "Change control",
            "Sensitive actions are gated before they run.",
            change_html,
        ),
    ]


def sections_markdown(sections: Sequence[Mapping[str, Any]]) -> str:
    """Render the segmented Admin sections."""
    if not sections:
        return '<div class="genai-card genai-muted">No administrative sections available.</div>'
    return (
        '<div class="genai-admin-sections">'
        + "".join(section_card_markdown(section) for section in sections)
        + "</div>"
    )


def change_control_markdown() -> str:
    """Explain the explicit confirmation gate for tenant policy changes."""
    return (
        '<section class="genai-card genai-admin-change"><h4>Before you update</h4>'
        "<p>Select a tenant, set an optional budget cap, then tick the confirmation "
        "checkbox to enable the update button.</p></section>"
    )


def admin_view_models(
    tenants_data: Any,
    users_data: Any,
    audit_data: Any,
    access_data: Any = None,
) -> Dict[str, Any]:
    """Build every Admin screen view model from the public API payloads."""
    tenants_payload = _mapping(tenants_data)
    users_payload = _mapping(users_data)
    audit_payload = _mapping(audit_data)
    tenant_models = tenant_cards(tenants_payload)
    user_models = user_rows(users_payload)
    audit_models = recent_audit_rows(audit_payload)
    alerts = admin_banners(tenants_payload, users_payload)
    sections = section_cards(
        tenant_cards_markdown(tenant_models),
        user_table_markdown(user_models),
        audit_table_markdown(audit_models),
        change_control_markdown(),
    )
    isolation = bool(tenants_payload.get("enabled"))
    directory = bool(users_payload.get("enabled"))
    kpis = kpi_strip(
        [
            {
                "label": "Tenant isolation",
                "value": "Enabled" if isolation else "Disabled",
                "status": badge_model("success" if isolation else "warning", "On" if isolation else "Off"),
            },
            {"label": "Tenants", "value": len(tenant_models)},
            {
                "label": "Directory",
                "value": "Enabled" if directory else "Disabled",
                "status": badge_model("success" if directory else "neutral", "On" if directory else "Off"),
            },
            {
                "label": "Active users",
                "value": sum(1 for row in user_models if row["status"] == "Active"),
            },
            {"label": "Recent events", "value": len(audit_models)},
        ]
    )
    return {
        "kpis": kpis,
        "tenants": tenant_models,
        "users": user_models,
        "audit": audit_models,
        "banners": alerts,
        "banners_markdown": banners_markdown(alerts),
        "sections": sections,
        "sections_markdown": sections_markdown(sections),
        "raw": redact_payload(
            {
                "tenants": tenants_payload,
                "users": users_payload,
                "audit": audit_payload,
                "access": _mapping(access_data),
            }
        ),
    }
