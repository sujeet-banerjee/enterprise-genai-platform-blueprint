"""Pure structured view models for the HITL Approvals screen (issue #249).

No Streamlit or backend imports. Helpers consume already-redacted approval
records and return escaped HTML fragments for thin renderers in ``ui/app.py``.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode

from ui.approvals import (
    DEFAULT_SLA_CRITICAL_HOURS,
    DEFAULT_SLA_WARNING_HOURS,
    approval_rows,
    decision_payload,
    evidence_links,
    sla_bucket,
)
from ui.components import (
    badge_model,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    kpi_strip_markdown,
    redact_payload,
    section_card_markdown,
    section_card_model,
)

MAX_METADATA_ROWS = 24
MAX_DECISION_ROWS = 10
MAX_EVIDENCE_CHIPS = 12

__all__ = [
    "approval_detail_view",
    "context_policy_panels",
    "decision_confirmation_markdown",
    "decision_confirmation_view",
    "decision_history_markdown",
    "evidence_chips_markdown",
    "flatten_metadata",
    "request_summary_markdown",
    "request_summary_view",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def flatten_metadata(value: Any, prefix: str = "", max_rows: int = MAX_METADATA_ROWS) -> Dict[str, Any]:
    """Flatten nested metadata into bounded, dotted key-value pairs."""
    rows: Dict[str, Any] = {}
    if not isinstance(value, Mapping):
        if value is not None:
            rows[prefix or "value"] = value
        return rows
    for raw_key, item in value.items():
        key = _text(raw_key) or "unnamed"
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping) and item:
            rows.update(flatten_metadata(item, path, max_rows))
        elif isinstance(item, (list, tuple)) and item:
            for index, element in enumerate(item):
                element_path = f"{path}.{index}"
                if isinstance(element, (Mapping, list, tuple)) and element:
                    rows.update(flatten_metadata(element, element_path, max_rows))
                else:
                    rows[element_path] = element
        else:
            rows[path] = item
        if len(rows) >= max_rows:
            break
    return dict(list(rows.items())[:max_rows])


def metadata_rows(value: Any, max_rows: int = MAX_METADATA_ROWS) -> List[Dict[str, Any]]:
    return key_value_rows(flatten_metadata(value, max_rows=max_rows))


def _status_badge(status: Any, label: Any = None) -> Dict[str, Any]:
    key = _text(status).lower()
    badge = badge_model(key, label or key or "unknown")
    if "approv" in key:
        badge["tone"] = "success"
    elif "reject" in key or "denied" in key:
        badge["tone"] = "danger"
    elif key in {"critical", "block", "blocked"}:
        badge["tone"] = "danger"
    elif key == "warning":
        badge["tone"] = "warning"
    elif key == "ok":
        badge["tone"] = "success"
    return badge


def request_summary_view(
    record: Any,
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> Dict[str, Any]:
    source = _mapping(record)
    rows = approval_rows([source], now, warning_hours, critical_hours)
    row = rows[0] if rows else {}
    bucket = sla_bucket(source, now, warning_hours, critical_hours)
    status = _text(row.get("status")) or "unknown"
    sla = _text(row.get("sla")) or "Unknown"
    kpis = kpi_strip(
        [
            {
                "label": "Status",
                "value": status.replace("_", " ").title(),
                "status": _status_badge(status),
            },
            {
                "label": "SLA",
                "value": sla,
                "status": _status_badge(bucket, sla),
            },
            {"label": "Action", "value": _text(row.get("action")) or "-"},
            {"label": "Requester", "value": _text(row.get("requester")) or "-"},
            {"label": "Tenant", "value": _text(row.get("tenant")) or "-"},
        ]
    )
    details = key_value_rows(
        {
            "Request ID": _text(row.get("request_id")) or "-",
            "Reason": _text(row.get("reason")) or "-",
            "Created": _text(row.get("created")) or "-",
            "Age": _text(row.get("age")) or "-",
            "Policy": _text(row.get("policy")) or "-",
            "Workspace": _text(row.get("workspace")) or "-",
            "App": _text(row.get("app")) or "-",
        },
        redact=False,
    )
    return {
        "kpis": kpis,
        "rows": details,
        "markdown": section_card_markdown(
            section_card_model(
                title="Approval request summary",
                description="Status, SLA, action and ownership for this HITL request.",
                body_html=kpi_strip_markdown(kpis) + key_value_markdown(details),
            )
        ),
    }


def request_summary_markdown(
    record: Any,
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> str:
    return str(
        request_summary_view(record, now, warning_hours, critical_hours)["markdown"]
    )


def context_policy_panels(record: Any) -> Dict[str, str]:
    source = _mapping(record)
    context_rows = metadata_rows(source.get("context"))
    policy_rows = metadata_rows(source.get("policy"))
    return {
        "context": key_value_markdown(
            context_rows,
            title="Request context",
            description="Redacted metadata supplied with the approval request.",
        ),
        "policy": key_value_markdown(
            policy_rows,
            title="Policy metadata",
            description="Resolved policy bundle and decision requirements.",
        ),
    }


def evidence_chips_markdown(links: Any, max_chips: int = MAX_EVIDENCE_CHIPS) -> str:
    chips: List[str] = []
    for raw_link in list(links or [])[:max_chips]:
        link = _mapping(raw_link)
        kind = _text(link.get("kind")) or "correlation"
        value = _text(link.get("value"))
        if not value:
            continue
        lower = kind.lower()
        if "audit" in lower:
            screen, param = "Audit", "audit_request"
        else:
            screen, param = "Traces", "traces_request_id"
        query = escape(urlencode({"screen": screen, param: value}), quote=True)
        label = escape(f"{kind}: {value}")
        chips.append(
            f'<a class="genai-chip genai-chip-link" href="?{query}" '
            f'title="Open in {escape(screen)}">{label}</a>'
        )
    if not chips:
        return '<div class="genai-card genai-muted">No correlation ids recorded.</div>'
    return f'<div class="genai-evidence-chips">{"".join(chips)}</div>'


def decision_history_markdown(record: Any, max_entries: int = MAX_DECISION_ROWS) -> str:
    source = _mapping(record)
    context = _mapping(source.get("context"))
    decisions = source.get("decisions") or context.get("decisions") or []
    if not isinstance(decisions, (list, tuple)):
        decisions = [decisions]
    entries: List[str] = []
    for index, raw_entry in enumerate(list(decisions)[:max_entries], 1):
        entry = _mapping(raw_entry)
        label = _text(entry.get("decision")) or _text(entry.get("outcome")) or "recorded"
        rows = metadata_rows(entry)
        entries.append(
            '<details class="genai-raw-record">'
            f"<summary>Decision {index}: {escape(label)}</summary>"
            f"{key_value_markdown(rows)}</details>"
        )
    if not entries:
        return '<div class="genai-card genai-muted">No decision history recorded yet.</div>'
    return f'<div class="genai-decision-history">{"".join(entries)}</div>'


def approval_detail_view(
    record: Any,
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> Dict[str, Any]:
    source = redact_payload(_mapping(record))
    panels = context_policy_panels(source)
    return {
        "summary": request_summary_markdown(source, now, warning_hours, critical_hours),
        "context": str(panels["context"]),
        "policy": str(panels["policy"]),
        "evidence": evidence_chips_markdown(evidence_links(source)),
        "decisions": decision_history_markdown(source),
        "raw": source,
    }


def decision_confirmation_view(
    record: Any,
    decision: Any,
    reviewer: Any = None,
    note: Any = None,
) -> Dict[str, Any]:
    try:
        payload = decision_payload(decision, reviewer, note)
    except ValueError:
        payload = {"decision": "invalid"}
    choice = _text(payload.get("decision")) or "invalid"
    rows = key_value_rows(
        {
            "Request ID": _text(_mapping(record).get("request_id")) or "-",
            "Decision": choice,
            "Reviewer": _text(payload.get("decided_by")) or "not provided",
            "Note": _text(payload.get("note")) or "none",
            "Scope": "Single request",
            "Reversible": "No - the decision is audited",
        },
        redact=False,
    )
    heading = f"Confirm {choice}"
    return {
        "decision": choice,
        "rows": rows,
        "markdown": section_card_markdown(
            section_card_model(
                title=heading,
                description="Review the decision before submitting it.",
                body_html=key_value_markdown(rows),
            )
        ),
    }


def decision_confirmation_markdown(
    record: Any,
    decision: Any,
    reviewer: Any = None,
    note: Any = None,
) -> str:
    return str(decision_confirmation_view(record, decision, reviewer, note)["markdown"])
