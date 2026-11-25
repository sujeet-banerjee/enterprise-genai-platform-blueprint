"""Structured Access / RBAC presentation helpers (issue #251).

Pure view models for the console's Access screen. No Streamlit or backend
imports; all values are escaped at render time and secrets are masked.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ui.components import (
    badge_markdown,
    badge_model,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    redact_payload,
)

CAPABILITY_GROUPS: Sequence[tuple[str, tuple[str, ...]]] = (
    (
        "Use the platform",
        ("query", "batch", "evaluate", "experiment"),
    ),
    (
        "Configure and inspect",
        ("rebuild", "introspect", "governance"),
    ),
    (
        "Oversight",
        ("audit", "approve", "admin"),
    ),
)

CAPABILITY_NOTES: Mapping[str, str] = {
    "query": "Ask a single question and read the answer.",
    "batch": "Submit several questions in one request.",
    "evaluate": "Score answers against your own criteria.",
    "experiment": "Launch and compare evaluation runs.",
    "rebuild": "Try a what-if component swap at runtime.",
    "introspect": "See the effective configuration and catalogs.",
    "governance": "View spend, policy status, and metrics.",
    "audit": "Read the append-only activity trail.",
    "approve": "Review and decide pending approvals.",
    "admin": "Manage tenants, users, and administrative changes.",
}

OTHER_GROUP = "Other grants"
_MAX_TEXT = 160


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _short(value: Any, limit: int = _MAX_TEXT) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [_short(item, 80) for item in value if _short(item, 80)]


def identity_summary(data: Any) -> Dict[str, Any]:
    """Resolve the identity, tenant, and policy fields shown in the summary card."""
    payload = _mapping(data)
    tenant = _mapping(payload.get("tenant"))
    top_k = payload.get("top_k_max")
    if not isinstance(top_k, int) or isinstance(top_k, bool):
        top_k_label = "Unbounded"
    else:
        top_k_label = str(top_k)
    return {
        "role": _short(payload.get("role")) or "-",
        "access_enabled": bool(payload.get("enabled")),
        "identity_enabled": bool(payload.get("identity_enabled")),
        "subject": _short(payload.get("subject")) or "-",
        "groups": _list(payload.get("groups")),
        "tenant_id": _short(tenant.get("id")) or "-",
        "workspace": _short(tenant.get("workspace")) or "-",
        "app": _short(tenant.get("app")) or "-",
        "top_k_max": top_k_label,
        "allowed_models": _list(payload.get("allowed_models")),
        "request_id": _short(payload.get("request_id")) or "-",
    }


def summary_markdown(data: Any) -> str:
    """Render the identity/tenant/role card instead of a raw payload dump."""
    summary = identity_summary(data)
    fields = {
        "role": summary["role"],
        "access_control": "Enabled" if summary["access_enabled"] else "Disabled",
        "sign_in": "SSO session" if summary["identity_enabled"] else "API key / default",
        "subject": summary["subject"],
        "groups": ", ".join(summary["groups"]) or "-",
        "tenant": summary["tenant_id"],
        "workspace": summary["workspace"],
        "app": summary["app"],
        "retrieval_depth": summary["top_k_max"],
        "allowed_models": ", ".join(summary["allowed_models"]) or "All configured models",
    }
    labels = {
        "role": "Role",
        "access_control": "Access control",
        "sign_in": "Sign-in",
        "subject": "Signed in as",
        "groups": "Groups",
        "tenant": "Tenant",
        "workspace": "Workspace",
        "app": "Application",
        "retrieval_depth": "Retrieval depth",
        "allowed_models": "Allowed models",
    }
    return key_value_markdown(
        key_value_rows(fields, labels=labels, redact=False),
        title="Current persona",
        description="Resolved for this request from the public access endpoint.",
    )


def granted_capabilities(data: Any) -> List[str]:
    """Return the sorted, de-duplicated capability names granted to the caller."""
    return sorted(set(_list(_mapping(data).get("capabilities"))))


def capability_groups(data: Any) -> List[Dict[str, Any]]:
    """Group all known capabilities into plain-language checklist sections."""
    granted = set(granted_capabilities(data))
    used: set[str] = set()
    groups: List[Dict[str, Any]] = []
    for label, names in CAPABILITY_GROUPS:
        items: List[Dict[str, Any]] = []
        for name in names:
            used.add(name)
            allowed = name in granted
            items.append(
                {
                    "name": name,
                    "allowed": allowed,
                    "badge": badge_model(
                        "allowed" if allowed else "neutral",
                        "Granted" if allowed else "Not granted",
                    ),
                    "note": CAPABILITY_NOTES.get(name, ""),
                }
            )
        groups.append({"label": label, "items": items})
    extras = sorted(granted - used)
    if extras:
        groups.append(
            {
                "label": OTHER_GROUP,
                "items": [
                    {
                        "name": name,
                        "allowed": True,
                        "badge": badge_model("allowed", "Granted"),
                        "note": "Additional capability granted to this role.",
                    }
                    for name in extras
                ],
            }
        )
    return groups


def capabilities_markdown(groups: Iterable[Mapping[str, Any]]) -> str:
    """Render grouped capability cards with granted/not-granted badges."""
    sections: List[str] = []
    for group in groups or []:
        items: List[str] = []
        for item in group.get("items") or []:
            badge = item.get("badge")
            badge_html = badge_markdown(badge) if isinstance(badge, Mapping) else ""
            name = escape(_short(item.get("name")) or "capability")
            note = escape(_short(item.get("note")))
            note_html = f'<span class="genai-access-note">{note}</span>' if note else ""
            items.append(
                f'<li class="genai-access-item">{badge_html}'
                f'<span class="genai-access-name">{name}</span>{note_html}</li>'
            )
        if not items:
            continue
        title = escape(_short(group.get("label")) or "Capabilities")
        sections.append(
            f'<section class="genai-card genai-access-group"><h4>{title}</h4>'
            f'<ul>{"".join(items)}</ul></section>'
        )
    if not sections:
        return '<div class="genai-card genai-muted">No capability information reported.</div>'
    return f'<div class="genai-access-groups">{"".join(sections)}</div>'


def policy_notes(data: Any) -> List[str]:
    """Explain the effective access policy without exposing raw field names."""
    summary = identity_summary(data)
    if summary["access_enabled"]:
        notes = ["Access control is on: every request is checked against your role."]
    else:
        notes = [
            "Access control is off: requests run with the default role and no capability checks."
        ]
    if summary["identity_enabled"]:
        notes.append(f"You are signed in as {summary['subject']} through single sign-on.")
        if summary["groups"]:
            notes.append("Your groups are " + ", ".join(summary["groups"]) + ".")
    else:
        notes.append("No single sign-on session is active; your role comes from the API key.")
    if summary["tenant_id"] != "-":
        notes.append(
            f"Your data is limited to tenant {summary['tenant_id']}, "
            f"workspace {summary['workspace']}, and app {summary['app']}."
        )
    else:
        notes.append("Single-tenant mode is active; no tenant scope is reported.")
    if summary["top_k_max"] == "Unbounded":
        notes.append("There is no explicit limit on how many documents can be retrieved.")
    else:
        notes.append(
            f"Retrieval returns at most {summary['top_k_max']} documents per request."
        )
    if summary["allowed_models"]:
        notes.append("Only these models are available: " + ", ".join(summary["allowed_models"]) + ".")
    else:
        notes.append("All configured models are available to this role.")
    return notes


def policy_markdown(notes: Iterable[Any]) -> str:
    """Render policy notes as a plain-language card."""
    items = [escape(_short(note, 320)) for note in notes or [] if _short(note, 320)]
    if not items:
        return '<div class="genai-card genai-muted">No policy notes available.</div>'
    return (
        '<section class="genai-card genai-access-notes"><h4>What this means</h4>'
        f'<ul>{"".join(f"<li>{note}</li>" for note in items)}</ul></section>'
    )


def access_view_models(data: Any) -> Dict[str, Any]:
    """Build every Access screen view model from the ``/v1/access`` payload."""
    payload = _mapping(data)
    summary = identity_summary(payload)
    groups = capability_groups(payload)
    notes = policy_notes(payload)
    kpis = kpi_strip(
        [
            {
                "label": "Access control",
                "value": "Enabled" if summary["access_enabled"] else "Disabled",
                "status": "success" if summary["access_enabled"] else "warning",
            },
            {"label": "Role", "value": summary["role"]},
            {
                "label": "Sign-in",
                "value": "SSO session" if summary["identity_enabled"] else "API key / default",
                "hint": summary["subject"] if summary["identity_enabled"] else "",
            },
            {"label": "Retrieval depth", "value": summary["top_k_max"]},
            {"label": "Capabilities granted", "value": len(granted_capabilities(payload))},
        ]
    )
    return {
        "kpis": kpis,
        "summary": summary,
        "summary_markdown": summary_markdown(payload),
        "groups": groups,
        "capabilities_markdown": capabilities_markdown(groups),
        "notes": notes,
        "policy_markdown": policy_markdown(notes),
        "raw": redact_payload(payload),
    }
