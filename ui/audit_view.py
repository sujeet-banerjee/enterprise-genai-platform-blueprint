"""Structured Audit presentation helpers (issue #250)."""

from __future__ import annotations

import csv
import io
import json
import re
from html import escape
from typing import Any, Dict, Iterable, List, Mapping

from ui.components import (
    badge_markdown,
    badge_model,
    format_timestamp,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    redact_payload,
)

_ACTOR_KEYS = ("actor", "user", "principal", "username", "sub", "decided_by", "performed_by")
_TENANT_KEYS = ("tenant", "tenant_id")
_REQUEST_KEYS = ("request_id", "trace_request_id", "event_request_id")
_EXPORT_FIELDS = (
    "timestamp",
    "event_type",
    "action",
    "outcome",
    "actor",
    "tenant",
    "request_id",
    "event_id",
)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*"
    r'|"?(?:api[_-]?key|secret|token|password)"?\s*[:=]\s*"?[^\s,;"]+)',
    re.IGNORECASE,
)
_FILENAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return text


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(source: Any, keys: Iterable[str]) -> str:
    data = _mapping(source)
    for key in keys:
        value = _text(data.get(key))
        if value:
            return value
    return ""


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def actor_of(event: Any) -> str:
    """Resolve the human/system actor from attribution, details or the event."""
    data = _mapping(event)
    attribution = _mapping(data.get("attribution"))
    details = _mapping(data.get("details"))
    for source in (data, attribution, details):
        found = _first(source, _ACTOR_KEYS)
        if found:
            return found[:160]
    return "-"


def tenant_of(event: Any) -> str:
    """Resolve the tenant dimension from the event or its attribution."""
    data = _mapping(event)
    attribution = _mapping(data.get("attribution"))
    for source in (data, attribution):
        found = _first(source, _TENANT_KEYS)
        if found:
            return found[:160]
    return "-"


def request_of(event: Any) -> str:
    """Resolve the request correlation id from the event or its details."""
    data = _mapping(event)
    details = _mapping(data.get("details"))
    for source in (data, details):
        found = _first(source, _REQUEST_KEYS)
        if found:
            return found[:160]
    return "-"


def event_badge(event: Any) -> Dict[str, Any]:
    """Build the event-type badge shown in the audit timeline."""
    return badge_model(_text(_mapping(event).get("event_type")) or "unknown")


def outcome_badge(event: Any) -> Dict[str, Any]:
    """Build the outcome badge shown in the audit timeline."""
    return badge_model(_text(_mapping(event).get("outcome")) or "unknown")


def detail_html(event: Any) -> str:
    """Render one expandable redacted audit detail block."""
    data = _mapping(event)
    summary = key_value_rows(
        {
            "event_id": data.get("event_id"),
            "timestamp": format_timestamp(data.get("timestamp")),
            "event_type": data.get("event_type"),
            "action": data.get("action"),
            "outcome": data.get("outcome"),
            "actor": actor_of(data),
            "tenant": tenant_of(data),
            "request_id": request_of(data),
        }
    )
    payload = json.dumps(_scrub(redact_payload(dict(data))), indent=2, sort_keys=True, default=str)
    return (
        '<details class="genai-audit-detail"><summary>Redacted detail</summary>'
        f"{key_value_markdown(summary, title='Event detail')}"
        f"<pre>{escape(payload)}</pre></details>"
    )


def timeline_rows(events: Iterable[Any]) -> List[Dict[str, Any]]:
    """Build timeline row view models from audit events."""
    rows: List[Dict[str, Any]] = []
    for event in events or []:
        data = _mapping(event)
        if not data:
            continue
        rows.append(
            {
                "timestamp": format_timestamp(data.get("timestamp")),
                "event_type": _text(data.get("event_type")) or "unknown",
                "event_badge": event_badge(data),
                "action": _text(data.get("action")) or "-",
                "outcome": _text(data.get("outcome")) or "unknown",
                "outcome_badge": outcome_badge(data),
                "actor": actor_of(data),
                "tenant": tenant_of(data),
                "request_id": request_of(data),
                "event_id": _text(data.get("event_id")) or "-",
                "detail_html": detail_html(data),
            }
        )
    return rows


def timeline_markdown(rows: Iterable[Mapping[str, Any]]) -> str:
    """Render the audit timeline table with badges and per-event disclosure."""
    items = list(rows or [])
    if not items:
        return (
            '<div class="genai-card genai-muted">No audit events returned '
            "(auditing may be disabled in <code>config/audit.yaml</code>).</div>"
        )
    header = (
        "<thead><tr><th>Time</th><th>Event type</th><th>Action</th><th>Outcome</th>"
        "<th>Actor</th><th>Tenant</th><th>Request</th><th>Detail</th></tr></thead>"
    )
    body: List[str] = []
    for row in items:
        badge = row.get("event_badge") if isinstance(row.get("event_badge"), Mapping) else badge_model(row.get("event_type"))
        outcome = row.get("outcome_badge") if isinstance(row.get("outcome_badge"), Mapping) else badge_model(row.get("outcome"))
        body.append(
            "<tr>"
            f'<td class="genai-audit-time">{escape(_text(row.get("timestamp")) or "-")}</td>'
            f"<td>{badge_markdown(badge)}</td>"
            f'<td>{escape(_text(row.get("action")) or "-")}</td>'
            f"<td>{badge_markdown(outcome)}</td>"
            f'<td>{escape(_text(row.get("actor")) or "-")}</td>'
            f'<td>{escape(_text(row.get("tenant")) or "-")}</td>'
            f'<td class="genai-audit-request">{escape(_text(row.get("request_id")) or "-")}</td>'
            f'<td>{row.get("detail_html") or ""}</td>'
            "</tr>"
        )
    return (
        '<div class="genai-audit-timeline"><table class="genai-audit-table">'
        f"{header}<tbody>{''.join(body)}</tbody></table></div>"
    )


def _count_rows(events: Iterable[Any], key: str) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for event in events or []:
        label = _text(_mapping(event).get(key)) or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def event_type_counts(events: Iterable[Any]) -> List[Dict[str, Any]]:
    """Count audit events by event type."""
    return _count_rows(events, "event_type")


def outcome_counts(events: Iterable[Any]) -> List[Dict[str, Any]]:
    """Count audit events by outcome."""
    return _count_rows(events, "outcome")


def export_rows(events: Iterable[Any]) -> List[Dict[str, str]]:
    """Build metadata-only, redacted rows for audit export."""
    rows: List[Dict[str, str]] = []
    for event in events or []:
        data = _mapping(event)
        if not data:
            continue
        rows.append(
            {
                "timestamp": format_timestamp(data.get("timestamp")),
                "event_type": _text(data.get("event_type")) or "unknown",
                "action": _text(data.get("action")) or "-",
                "outcome": _text(data.get("outcome")) or "unknown",
                "actor": actor_of(data),
                "tenant": tenant_of(data),
                "request_id": request_of(data),
                "event_id": _text(data.get("event_id")) or "-",
            }
        )
    return rows


def _safe_cell(value: Any) -> str:
    text = _text(value).replace("\r", " ").replace("\n", " ")
    if text[:1] in {"=", "+", "-", "@", "\t"}:
        return "'" + text
    return text


def export_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    """Serialize export rows to CSV with formula-injection guards."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(_EXPORT_FIELDS), lineterminator="\n")
    writer.writeheader()
    for row in rows or []:
        writer.writerow({field: _safe_cell(row.get(field)) for field in _EXPORT_FIELDS})
    return buffer.getvalue()


def export_json(rows: Iterable[Mapping[str, Any]]) -> str:
    """Serialize export rows to deterministic JSON."""
    return json.dumps(list(rows or []), indent=2, sort_keys=True, default=str)


def export_filename(kind: str = "csv", request_id: Any = "", event_type: Any = "") -> str:
    """Build a safe deterministic filename for an audit export."""
    parts = ["audit-events"]
    event_slug = _FILENAME_RE.sub("-", _text(event_type).lower()).strip("-")
    request_slug = _FILENAME_RE.sub("-", _text(request_id).lower()).strip("-")
    if event_slug:
        parts.append(event_slug[:32])
    if request_slug:
        parts.append(request_slug[:24])
    suffix = "json" if _text(kind).lower() == "json" else "csv"
    return "-".join(parts) + "." + suffix


def audit_view_models(
    data: Any,
    request_id: Any = "",
    event_type: Any = "",
) -> Dict[str, Any]:
    """Build all Audit screen view models from the ``/v1/audit`` payload."""
    payload = _mapping(data)
    events = [event for event in (payload.get("events") or []) if _mapping(event)]
    rows = export_rows(events)
    timeline = timeline_rows(events)
    types = event_type_counts(events)
    outcomes = outcome_counts(events)
    enabled = bool(payload.get("enabled"))
    count = payload.get("count")
    if not isinstance(count, int):
        count = len(events)
    total = payload.get("total")
    if not isinstance(total, int):
        total = count
    kpis = kpi_strip(
        [
            {
                "label": "Audit enabled",
                "value": "yes" if enabled else "no",
                "status": "success" if enabled else "warning",
            },
            {"label": "Events returned", "value": count},
            {"label": "Total retained", "value": total},
            {"label": "Event types", "value": len(types)},
            {"label": "Outcomes", "value": len(outcomes)},
        ]
    )
    return {
        "kpis": kpis,
        "event_types": types,
        "outcomes": outcomes,
        "timeline": timeline,
        "timeline_markdown": timeline_markdown(timeline),
        "export": rows,
        "export_csv": export_csv(rows),
        "export_json": export_json(rows),
        "csv_filename": export_filename("csv", request_id, event_type),
        "json_filename": export_filename("json", request_id, event_type),
    }
