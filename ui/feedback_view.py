"""Structured Feedback presentation view models (#254).

This module is intentionally free of Streamlit, backend and network imports so
the review queue can be tested as a pure view model. It turns bounded feedback
annotations into KPIs, reason breakdowns, status/reason badges, a review card,
redacted exports and a redacted raw payload.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ui.components import (
    alert_markdown,
    alert_model,
    badge_markdown,
    badge_model,
    empty_alert_model,
    format_timestamp,
    key_value_markdown,
    key_value_rows,
    kpi_model,
    kpi_strip_markdown,
    redact_payload,
)
from ui.feedback import (
    ANY_PROMOTED,
    ANY_REASON,
    FLAG_REASONS,
    REASON_LABELS,
    export_annotations_csv,
    export_annotations_json,
    export_filename,
    filter_annotations,
    find_annotation,
    normalize_annotations,
    reason_label,
    reason_summary,
)

RAW_EXPANDER_LABEL = "Raw (redacted)"
PRIVACY_NOTE = (
    "Notes are redacted and stay out of share links; only request id, flag and reason are shared. "
    "Exports and raw payloads are redacted before leaving the console."
)
_EMPTY_MESSAGE = "No flagged runs match the current filters. Flag a run from Query Studio or Traces."
_MAX_ROWS = 50
_MAX_TEXT = 180
_REASON_TONES = {
    "incorrect": "danger",
    "unsupported": "warning",
    "outdated": "warning",
    "unsafe": "danger",
    "off_topic": "warning",
    "other": "neutral",
}
_DETAIL_LABELS = {
    "request_id": "Request id",
    "query": "Query",
    "flag": "Flagged",
    "reason": "Reason",
    "note": "Reviewer note",
    "tags": "Tags",
    "failure_type": "Failure type",
    "tenant": "Tenant",
    "user": "User",
    "promoted": "Promoted",
    "created_at": "Created",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _short(value: Any, limit: int = _MAX_TEXT) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def redact_feedback_payload(value: Any) -> Any:
    """Mask secret-like keys and obvious secret literals in a feedback payload."""
    safe = redact_payload(value)
    if isinstance(safe, Mapping):
        return {str(key): redact_feedback_payload(item) for key, item in safe.items()}
    if isinstance(safe, list):
        return [redact_feedback_payload(item) for item in safe]
    if isinstance(safe, str):
        return _clean_secret_literals(safe)
    return safe


_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{4,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*)"
)


def _clean_secret_literals(value: str) -> str:
    return _SECRET_VALUE_RE.sub("[REDACTED]", value)


def state_badge(annotation: Mapping[str, Any]) -> Dict[str, Any]:
    if annotation.get("promoted"):
        return badge_model("success", "promoted")
    if annotation.get("flag"):
        return badge_model("warning", "flagged")
    return badge_model("neutral", "noted")


def reason_badge(annotation: Mapping[str, Any]) -> Dict[str, Any]:
    reason = str(annotation.get("reason") or "other")
    return badge_model(_REASON_TONES.get(reason, "neutral"), reason_label(reason))


def feedback_kpis(annotations: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    summary = reason_summary(list(annotations))
    return [
        kpi_model("Total annotations", summary["total"]),
        kpi_model("Flagged", summary["flagged"]),
        kpi_model("Promoted", summary["promoted"]),
        kpi_model(
            "Open flags",
            max(summary["flagged"] - summary["promoted"], 0),
            hint="flagged but not promoted",
        ),
    ]


def reason_breakdown(annotations: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    summary = reason_summary(list(annotations))
    return [
        {"label": REASON_LABELS.get(reason, reason), "count": int(summary["by_reason"].get(reason, 0))}
        for reason in FLAG_REASONS
    ]


def reason_chart_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-feedback-reasons genai-muted">No reasons recorded.</div>'
    counts = [int(row.get("count") or 0) for row in rows]
    ceiling = max(counts, default=0) or 1
    parts = ['<div class="genai-feedback-reasons">']
    for row in rows:
        count = max(int(row.get("count") or 0), 0)
        percent = min(100, round(count * 100 / ceiling)) if count else 0
        label = escape(_text(row.get("label")) or "other")
        parts.append(
            '<div class="genai-feedback-reason">'
            f'<div class="genai-feedback-reason-label">{label}</div>'
            '<div class="genai-feedback-reason-track">'
            f'<span class="genai-feedback-reason-bar" style="width: {percent}%"></span>'
            "</div>"
            f'<div class="genai-feedback-reason-count">{count}</div>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def feedback_rows(
    annotations: Iterable[Mapping[str, Any]], max_rows: int = _MAX_ROWS
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in normalize_annotations(list(annotations))[:max_rows]:
        rows.append(
            {
                "request_id": _short(item["request_id"], 80),
                "reason_badge": badge_markdown(reason_badge(item)),
                "state_badge": badge_markdown(state_badge(item)),
                "query": _short(item["query"]),
                "note": _short(item["note"]),
                "failure_type": _short(item["failure_type"], 80),
                "tenant": _short(item["tenant"], 80),
                "user": _short(item["user"], 80),
                "created_at": format_timestamp(item["created_at"]),
                "tags": ", ".join(item["tags"]),
            }
        )
    return rows


def feedback_table_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return alert_markdown(empty_alert_model(_EMPTY_MESSAGE))
    headers = [
        "Request id",
        "Reason",
        "State",
        "Query",
        "Reviewer note",
        "Tenant",
        "User",
        "Created",
    ]
    parts = ['<table class="genai-table genai-feedback-table"><thead><tr>']
    parts.extend(f"<th>{escape(header)}</th>" for header in headers)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        reason_html = row.get("reason_badge") or ""
        state_html = row.get("state_badge") or ""
        parts.append("<tr>")
        parts.append(f"<td><code>{escape(_text(row.get('request_id')) or '-')}</code></td>")
        parts.append(f"<td>{reason_html}</td>")
        parts.append(f"<td>{state_html}</td>")
        for key in ("query", "note", "tenant", "user", "created_at"):
            parts.append(f"<td>{escape(_text(row.get(key)) or '-')}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def selected_feedback_card(annotation: Optional[Mapping[str, Any]]) -> str:
    if not annotation:
        return '<div class="genai-card genai-muted">Select an annotated request to review it.</div>'
    rows = key_value_rows(annotation, labels=_DETAIL_LABELS)
    return key_value_markdown(
        rows,
        title=f"Request {_text(annotation.get('request_id')) or '-'}",
        description=PRIVACY_NOTE,
    )


def feedback_exports(annotations: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    items = normalize_annotations(list(annotations))
    if not items:
        return []
    return [
        {
            "label": "Export feedback (JSON)",
            "data": export_annotations_json(items),
            "file_name": export_filename("json"),
            "mime": "application/json",
            "key": "feedback_export_json",
        },
        {
            "label": "Export feedback (CSV)",
            "data": export_annotations_csv(items),
            "file_name": export_filename("csv"),
            "mime": "text/csv",
            "key": "feedback_export_csv",
        },
    ]


def feedback_view_models(
    annotations: Optional[Iterable[Mapping[str, Any]]] = None,
    *,
    reason: Any = ANY_REASON,
    promoted: Any = ANY_PROMOTED,
    search: Any = "",
    selected: Any = None,
) -> Dict[str, Any]:
    safe = normalize_annotations(list(annotations or []))
    filtered = filter_annotations(safe, reason=reason, promoted=promoted, search=search)
    selected_item = find_annotation(safe, selected)
    return {
        "annotations": safe,
        "filtered": filtered,
        "selected": selected_item,
        "kpis": feedback_kpis(safe),
        "kpis_markdown": kpi_strip_markdown(feedback_kpis(safe)),
        "reasons": reason_breakdown(safe),
        "reasons_markdown": reason_chart_markdown(reason_breakdown(safe)),
        "rows": feedback_rows(filtered),
        "table_markdown": feedback_table_markdown(feedback_rows(filtered)),
        "selected_markdown": selected_feedback_card(selected_item),
        "privacy_markdown": alert_markdown(
            alert_model("Privacy & redaction", PRIVACY_NOTE, tone="info")
        ),
        "exports": feedback_exports(safe),
        "filtered_count": len(filtered),
        "total_count": len(safe),
        "raw": redact_feedback_payload(
            {
                "annotations": safe,
                "filtered": filtered,
                "selected": selected_item,
                "summary": reason_summary(safe),
            }
        ),
        "expander_label": RAW_EXPANDER_LABEL,
    }
