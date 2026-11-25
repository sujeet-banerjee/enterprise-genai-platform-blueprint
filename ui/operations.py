"""Pure view models for the async operations console (issue #280).

This module is Streamlit-free and backend-free so the operations contract can be
unit-tested without a browser. The console still reaches the backend only
through :mod:`ui.client`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional
from uuid import uuid4

ACTIVE_OPERATION_STATUSES = ("queued", "running")
TERMINAL_OPERATION_STATUSES = ("completed", "failed", "cancelled")
KNOWN_OPERATION_STATUSES = ACTIVE_OPERATION_STATUSES + TERMINAL_OPERATION_STATUSES

STATUS_TONES = {
    "queued": "neutral",
    "running": "info",
    "completed": "success",
    "failed": "danger",
    "cancelled": "warning",
}


def ensure_client_session(state: MutableMapping[str, Any]) -> str:
    """Return a stable anonymous possession token for owner-scoped operations."""
    value = str(state.get("client_session") or "").strip()
    if not value:
        value = f"ui-{uuid4().hex}"
        state["client_session"] = value
    return value


def normalize_operation(operation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a display-safe operation record with stable defaults."""
    source = dict(operation or {})
    status = str(source.get("status") or "queued").strip().lower() or "queued"
    raw_progress = source.get("progress")
    progress: Mapping[str, Any] = raw_progress if isinstance(raw_progress, dict) else {}
    return {
        "id": str(source.get("id") or source.get("request_id") or ""),
        "request_id": str(source.get("request_id") or source.get("id") or ""),
        "kind": str(source.get("kind") or "query"),
        "status": status,
        "stage": str(source.get("stage") or progress.get("stage") or status),
        "message": str(progress.get("message") or status.capitalize()),
        "created_at": source.get("created_at"),
        "started_at": source.get("started_at"),
        "finished_at": source.get("finished_at"),
        "updated_at": source.get("updated_at") or source.get("created_at"),
        "tenant": str(source.get("tenant") or ""),
        "workspace": str(source.get("workspace") or ""),
        "app": str(source.get("app") or ""),
        "result": source.get("result") if isinstance(source.get("result"), dict) else None,
        "error": str(source.get("error") or ""),
        "failure_type": str(source.get("failure_type") or ""),
        "failure_tags": [str(tag) for tag in (source.get("failure_tags") or [])],
    }


def is_active_operation(operation: Optional[Mapping[str, Any]]) -> bool:
    return normalize_operation(operation)["status"] in ACTIVE_OPERATION_STATUSES


def is_terminal_operation(operation: Optional[Mapping[str, Any]]) -> bool:
    return normalize_operation(operation)["status"] in TERMINAL_OPERATION_STATUSES


def operation_result(operation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a detached result payload for terminal operations."""
    normalized = normalize_operation(operation)
    result = dict(normalized["result"] or {})
    if not result:
        return {}
    if not result.get("request_id"):
        result["request_id"] = normalized["request_id"]
    return result


def operation_failure(operation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return the governed failure envelope represented by an operation."""
    normalized = normalize_operation(operation)
    return {
        "request_id": normalized["request_id"],
        "error": normalized["error"],
        "failure_type": normalized["failure_type"],
        "failure_tags": normalized["failure_tags"],
    }


def format_operation_time(value: Any) -> str:
    """Format an epoch timestamp without relying on the caller's locale."""
    try:
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return "-"
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def operation_badge(operation: Optional[Mapping[str, Any]]) -> str:
    """Render a semantic status badge with escaped text."""
    normalized = normalize_operation(operation)
    tone = STATUS_TONES.get(normalized["status"], "neutral")
    return (
        f'<span class="genai-status genai-status--{escape(tone, quote=True)}">'
        f"{escape(normalized['status'], quote=True)}</span>"
    )


def operation_rows(operations: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Build compact rows for the in-progress operations panel."""
    return [
        {
            "id": item["id"],
            "kind": item["kind"],
            "status": item["status"],
            "stage": item["stage"],
            "tenant": item["tenant"] or "-",
            "updated": format_operation_time(item["updated_at"]),
        }
        for item in (normalize_operation(op) for op in operations or [])
        if item["id"]
    ]


def operations_summary(operations: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Count in-progress, recent and experiment operations."""
    items = [normalize_operation(op) for op in operations or []]
    return {
        "total": len(items),
        "active": sum(1 for item in items if item["status"] in ACTIVE_OPERATION_STATUSES),
        "completed": sum(1 for item in items if item["status"] == "completed"),
        "failed": sum(1 for item in items if item["status"] == "failed"),
        "experiments": sum(1 for item in items if item["kind"] == "experiment"),
    }


def operations_table_markdown(operations: Iterable[Mapping[str, Any]]) -> str:
    """Render an escaped HTML table of owner-scoped operations."""
    rows = operation_rows(operations)
    if not rows:
        return '<p class="genai-muted">No operations in the recent window.</p>'
    header = "<tr><th>ID</th><th>Kind</th><th>Status</th><th>Stage</th><th>Tenant</th><th>Updated</th></tr>"
    body = "".join(
        "<tr>"
        f"<td>{escape(str(row['id']), quote=True)}</td>"
        f"<td>{escape(str(row['kind']), quote=True)}</td>"
        f"<td>{escape(str(row['status']), quote=True)}</td>"
        f"<td>{escape(str(row['stage']), quote=True)}</td>"
        f"<td>{escape(str(row['tenant']), quote=True)}</td>"
        f"<td>{escape(str(row['updated']), quote=True)}</td>"
        "</tr>"
        for row in rows
    )
    return (
        '<div class="genai-table-scroll">'
        f'<table class="genai-table"><thead>{header}</thead><tbody>{body}</tbody></table>'
        "</div>"
    )


def pending_operation_markdown(operation: Optional[Mapping[str, Any]]) -> str:
    """Render the immediate request id and coarse progress after submit."""
    item = normalize_operation(operation)
    request_id = escape(item["request_id"] or item["id"] or "-", quote=True)
    return (
        '<div class="genai-card genai-card--pending">'
        f'<div class="genai-card__title">Operation submitted: <code>{request_id}</code></div>'
        f'<div class="genai-card__meta">{operation_badge(item)} '
        f"stage: {escape(item['stage'], quote=True)}</div>"
        "</div>"
    )
