"""Pure helpers for the HITL approvals console (issues #163, #164).

This module deliberately has no Streamlit or backend imports. It normalizes the
approval API payloads, redacts secrets before the UI can render them and builds
copyable evidence/deep-link hooks without implementing cross-screen navigation.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

STATUS_OPTIONS = ("pending", "approved", "rejected", "all")
DEFAULT_STATUS = "pending"
DECISIONS = ("approved", "rejected")
ANY_VALUE = "(any)"
DEFAULT_SORT = "Newest first"
SORT_OPTIONS = (
    "Newest first",
    "Oldest first",
    "Longest pending first",
    "Shortest pending first",
)
AGE_FILTER_OPTIONS = ("Any age", "> 1 hour", "> 4 hours", "> 24 hours")
AGE_FILTER_HOURS = {
    "Any age": 0.0,
    "> 1 hour": 1.0,
    "> 4 hours": 4.0,
    "> 24 hours": 24.0,
}
PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
DEFAULT_SLA_WARNING_HOURS = 4.0
DEFAULT_SLA_CRITICAL_HOURS = 24.0
SAFE_EXPORT_FIELDS = (
    "request_id",
    "status",
    "action",
    "reason",
    "policy",
    "requester",
    "tenant",
    "workspace",
    "app",
    "created_at",
    "created_at_utc",
    "age_seconds",
    "sla",
    "decided_at",
    "decided_at_utc",
    "decided_by",
    "decision_note",
    "evidence_ids",
)

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|authorization|bearer"
    r"|access[_-]?token|refresh[_-]?token|^token$|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*)"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ID_RE = re.compile(r"[^A-Za-z0-9._:@/+=-]+")
_EVIDENCE_KEYS = frozenset(
    {
        "request_id",
        "trace_request_id",
        "audit_request_id",
        "run_id",
        "experiment_id",
        "trace_id",
        "span_id",
        "correlation_id",
    }
)
_REQUESTER_KEYS = (
    "requester",
    "requested_by",
    "user",
    "user_id",
    "subject",
    "principal",
    "owner",
)
_TENANT_KEYS = ("tenant", "tenant_id")
_WORKSPACE_KEYS = ("workspace", "workspace_id")
_APP_KEYS = ("app", "app_id", "application")
_POLICY_KEYS = ("policy_id", "bundle", "action")
_POLICY_FILTER_KEYS = ("policy_id", "bundle")


def normalize_status(value: Any) -> str:
    """Return one of :data:`STATUS_OPTIONS`; pending is the safe default."""
    status = str(value or "").strip().lower()
    return status if status in STATUS_OPTIONS else DEFAULT_STATUS


def status_filter(value: Any) -> Optional[str]:
    """Map the console selector to the API ``status`` query parameter."""
    status = normalize_status(value)
    return None if status == "all" else status


def _clean_id(value: Any) -> str:
    if value is None:
        return ""
    return _ID_RE.sub("", str(value).strip())[:200]


def _redact_text(value: Any, limit: int = 500) -> str:
    text = _CONTROL_RE.sub("", str(value or ""))
    return _SECRET_VALUE_RE.sub("[REDACTED]", text).strip()[:limit]


def redact_approval(value: Any) -> Any:
    """Recursively mask secret-looking keys/values before rendering."""
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            redacted[name] = (
                "[REDACTED]" if _SECRET_KEY_RE.search(name) else redact_approval(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_approval(item) for item in value]
    if isinstance(value, tuple):
        return [redact_approval(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def format_timestamp(value: Any) -> str:
    """Render an epoch timestamp (seconds) as a compact UTC string."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return _redact_text(value, 80)
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def _utc_iso(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_of(record: Mapping[str, Any]) -> str:
    return str(record.get("status") or "").strip().lower()


def _find_value(value: Any, keys: Sequence[str], depth: int = 0) -> Any:
    if depth > 2 or not isinstance(value, Mapping):
        return None
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return item
    for wrapper in ("context", "request", "attribution", "metadata", "principal"):
        found = _find_value(value.get(wrapper), keys, depth + 1)
        if found not in (None, ""):
            return found
    return None


def requester_value(record: Mapping[str, Any]) -> str:
    """Best-effort requester label from optional top-level/context metadata."""
    return _redact_text(_find_value(record, _REQUESTER_KEYS), 120)


def tenant_value(record: Mapping[str, Any]) -> str:
    """Best-effort tenant label from optional top-level/context metadata."""
    return _redact_text(_find_value(record, _TENANT_KEYS), 80)


def workspace_value(record: Mapping[str, Any]) -> str:
    """Best-effort workspace label from optional top-level/context metadata."""
    return _redact_text(_find_value(record, _WORKSPACE_KEYS), 80)


def app_value(record: Mapping[str, Any]) -> str:
    """Best-effort application label from optional metadata."""
    return _redact_text(_find_value(record, _APP_KEYS), 80)


def policy_values(record: Mapping[str, Any]) -> List[str]:
    """Return filterable policy identifiers without leaking raw metadata."""
    policy = record.get("policy")
    if not isinstance(policy, Mapping):
        return []
    values: List[str] = []
    for key in _POLICY_FILTER_KEYS:
        value = policy.get(key)
        if value:
            values.append(_redact_text(value, 120))
    return values


def policy_summary(policy: Any) -> str:
    """Summarize policy id/bundle/action/labels for the queue table."""
    if not isinstance(policy, Mapping):
        return ""
    parts: List[str] = []
    for key in _POLICY_KEYS:
        value = policy.get(key)
        if value:
            parts.append(f"{key}={_redact_text(value, 80)}")
    labels = policy.get("labels")
    if isinstance(labels, (list, tuple, set)):
        if labels:
            parts.append(
                "labels=" + ",".join(_redact_text(item, 60) for item in labels)
            )
    elif labels:
        parts.append("labels=" + _redact_text(labels, 120))
    return " | ".join(parts)


def age_seconds(record: Mapping[str, Any], now: Optional[float] = None) -> Optional[float]:
    """Seconds from creation to decision (or now for pending requests)."""
    created = _as_number(record.get("created_at"))
    if created is None:
        return None
    decided = _as_number(record.get("decided_at"))
    if decided is not None and _status_of(record) in DECISIONS:
        return max(0.0, decided - created)
    end = float(now) if now is not None else time.time()
    return max(0.0, end - created)


def age_label(seconds: Optional[float]) -> str:
    """Compact human duration such as ``3h 12m`` or ``<1m``."""
    if seconds is None:
        return ""
    value = max(0.0, float(seconds))
    if value < 60:
        return "<1m"
    minutes = int(value // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, remainder = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {remainder}m" if remainder else f"{hours}h"
    days, remaining_hours = divmod(hours, 24)
    return f"{days}d {remaining_hours}h" if remaining_hours else f"{days}d"


def _bucket_seconds(hours: Any, fallback: float) -> float:
    try:
        parsed = float(hours)
    except (TypeError, ValueError):
        return fallback * 3600.0
    if parsed != parsed:
        return fallback * 3600.0
    return max(0.0, parsed) * 3600.0


def sla_bucket(
    record: Mapping[str, Any],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> str:
    """Classify an approval as ok/warning/critical/decided/unknown."""
    if _status_of(record) in DECISIONS:
        return "decided"
    seconds = age_seconds(record, now)
    if seconds is None:
        return "unknown"
    warning = _bucket_seconds(warning_hours, DEFAULT_SLA_WARNING_HOURS)
    critical = max(warning, _bucket_seconds(critical_hours, DEFAULT_SLA_CRITICAL_HOURS))
    if seconds >= critical:
        return "critical"
    if seconds >= warning:
        return "warning"
    return "ok"


def sla_label(bucket: str) -> str:
    """Human label for an SLA bucket."""
    return {
        "ok": "OK",
        "warning": "Warning",
        "critical": "Critical",
        "decided": "Decided",
        "unknown": "Unknown",
    }.get(str(bucket or ""), "Unknown")


def sla_summary(
    records: Sequence[Mapping[str, Any]],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> Dict[str, int]:
    """Count records by SLA bucket for the header tiles."""
    counts = {"ok": 0, "warning": 0, "critical": 0, "decided": 0, "unknown": 0}
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        bucket = sla_bucket(record, now, warning_hours, critical_hours)
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def approval_rows(
    records: Sequence[Mapping[str, Any]],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> List[Dict[str, Any]]:
    """Build bounded, redacted queue rows from ``GET /v1/approvals``."""
    rows: List[Dict[str, Any]] = []
    moment = float(now) if now is not None else time.time()
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        age = age_seconds(record, moment)
        rows.append(
            {
                "request_id": _clean_id(record.get("request_id")),
                "status": _redact_text(record.get("status"), 40),
                "action": _redact_text(record.get("action"), 80),
                "reason": _redact_text(record.get("reason"), 200),
                "policy": policy_summary(record.get("policy")),
                "requester": requester_value(record),
                "tenant": tenant_value(record),
                "workspace": workspace_value(record),
                "app": app_value(record),
                "created": format_timestamp(record.get("created_at")),
                "age_seconds": int(age) if age is not None else None,
                "age": age_label(age),
                "sla": sla_label(
                    sla_bucket(record, moment, warning_hours, critical_hours)
                ),
                "decided_by": _redact_text(record.get("decided_by"), 80),
            }
        )
    return rows


def summary_counts(records: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """Count requests by status plus a total for header tiles."""
    counts = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "other": 0}
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        counts["total"] += 1
        status = _status_of(record)
        if status in ("pending", "approved", "rejected"):
            counts[status] += 1
        else:
            counts["other"] += 1
    return counts


def approval_filter_options(
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    """Collect stable filter option values from the current queue."""
    actions: set = set()
    policies: set = set()
    requesters: set = set()
    tenants: set = set()
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        action = _redact_text(record.get("action"), 80)
        if action:
            actions.add(action)
        policies.update(policy_values(record))
        requester = requester_value(record)
        if requester:
            requesters.add(requester)
        tenant = tenant_value(record)
        if tenant:
            tenants.add(tenant)
    return {
        "actions": sorted(actions),
        "policies": sorted(policies),
        "requesters": sorted(requesters),
        "tenants": sorted(tenants),
    }


def _matches(value: str, selected: Any) -> bool:
    choice = str(selected or ANY_VALUE).strip()
    if not choice or choice == ANY_VALUE:
        return True
    return value.strip().lower() == choice.lower()


def filter_approval_records(
    records: Sequence[Mapping[str, Any]],
    status: Any = "all",
    action: Any = ANY_VALUE,
    policy: Any = ANY_VALUE,
    requester: Any = ANY_VALUE,
    tenant: Any = ANY_VALUE,
    age: Any = AGE_FILTER_OPTIONS[0],
    search: str = "",
    now: Optional[float] = None,
) -> List[Mapping[str, Any]]:
    """Apply display-only queue filters (not an authorization boundary)."""
    selected_status = normalize_status(status)
    minimum_age = AGE_FILTER_HOURS.get(str(age or ""), 0.0) * 3600.0
    needle = _redact_text(search, 200).lower()
    moment = float(now) if now is not None else time.time()
    filtered: List[Mapping[str, Any]] = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        if selected_status != "all" and _status_of(record) != selected_status:
            continue
        record_action = _redact_text(record.get("action"), 80)
        if not _matches(record_action, action):
            continue
        if not any(_matches(item, policy) for item in policy_values(record)):
            if str(policy or ANY_VALUE) != ANY_VALUE:
                continue
        if not _matches(requester_value(record), requester):
            continue
        if not _matches(tenant_value(record), tenant):
            continue
        seconds = age_seconds(record, moment)
        if minimum_age and (seconds is None or seconds < minimum_age):
            continue
        if needle:
            haystack = " ".join(
                [
                    _clean_id(record.get("request_id")),
                    record_action,
                    _redact_text(record.get("reason"), 200),
                    policy_summary(record.get("policy")),
                    requester_value(record),
                    tenant_value(record),
                    workspace_value(record),
                    app_value(record),
                ]
            ).lower()
            if needle not in haystack:
                continue
        filtered.append(record)
    return filtered


def sort_approval_records(
    records: Sequence[Mapping[str, Any]],
    sort_by: Any = DEFAULT_SORT,
    now: Optional[float] = None,
) -> List[Mapping[str, Any]]:
    """Sort queue records deterministically; request id breaks ties."""
    choice = str(sort_by or DEFAULT_SORT)
    if choice not in SORT_OPTIONS:
        choice = DEFAULT_SORT
    moment = float(now) if now is not None else time.time()
    by_id = sorted(records or [], key=lambda item: _clean_id(item.get("request_id")))
    if choice == "Oldest first":
        return sorted(
            by_id,
            key=lambda item: _as_number(item.get("created_at")) or 0.0,
        )
    if choice == "Longest pending first":
        return sorted(
            by_id,
            key=lambda item: (
                age_seconds(item, moment) is not None,
                age_seconds(item, moment) or 0.0,
            ),
            reverse=True,
        )
    if choice == "Shortest pending first":
        return sorted(
            by_id,
            key=lambda item: (
                age_seconds(item, moment) is None,
                age_seconds(item, moment) or 0.0,
            ),
        )
    return sorted(
        by_id,
        key=lambda item: _as_number(item.get("created_at")) or 0.0,
        reverse=True,
    )


def paginate_approval_records(
    records: Sequence[Mapping[str, Any]],
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """Return one clamped page plus navigation metadata."""
    items = list(records or [])
    try:
        size = int(page_size)
    except (TypeError, ValueError):
        size = DEFAULT_PAGE_SIZE
    size = max(1, min(500, size))
    total = len(items)
    pages = (total + size - 1) // size if total else 0
    try:
        current = int(page)
    except (TypeError, ValueError):
        current = 1
    current = max(1, min(current, pages)) if pages else 1
    start = (current - 1) * size if pages else 0
    end = min(start + size, total)
    return {
        "items": items[start:end],
        "page": current,
        "page_size": size,
        "total": total,
        "pages": pages,
        "start": start,
        "end": end,
        "has_prev": pages > 0 and current > 1,
        "has_next": pages > 0 and current < pages,
    }


def pending_ids(records: Sequence[Mapping[str, Any]]) -> List[str]:
    """Unique pending request ids in queue order."""
    seen: set = set()
    ids: List[str] = []
    for record in records or []:
        if not isinstance(record, Mapping) or _status_of(record) != "pending":
            continue
        request_id = _clean_id(record.get("request_id"))
        if request_id and request_id not in seen:
            seen.add(request_id)
            ids.append(request_id)
    return ids


def select_pending_records(
    records: Sequence[Mapping[str, Any]],
    selected_ids: Sequence[Any],
) -> List[Mapping[str, Any]]:
    """Keep selected records that are still pending, in queue order."""
    selected = {_clean_id(item) for item in selected_ids or []}
    selected.discard("")
    out: List[Mapping[str, Any]] = []
    seen: set = set()
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        request_id = _clean_id(record.get("request_id"))
        if (
            request_id in selected
            and request_id not in seen
            and _status_of(record) == "pending"
        ):
            seen.add(request_id)
            out.append(record)
    return out


def bulk_confirmation_text(count: int, decision: str) -> str:
    """Explain the non-atomic, per-item semantics of a bulk decision."""
    choice = str(decision or "").strip().lower()
    if choice not in DECISIONS:
        choice = "decision"
    if count <= 0:
        return "Select at least one pending request."
    return (
        f"This submits '{choice}' for {count} request(s) one at a time. "
        "Requests may change state between review and submission; failures are "
        "reported per request and successful decisions are not rolled back."
    )


def bulk_result_row(
    request_id: Any,
    decision: Any,
    *,
    ok: bool,
    status: Any = "",
    failure_type: Any = "",
    error: Any = "",
) -> Dict[str, str]:
    """Build one redacted per-item bulk result row."""
    choice = str(decision or "").strip().lower()
    server_status = _redact_text(status, 40)
    outcome = "succeeded" if ok else "failed"
    detail = _redact_text(error, 300)
    if ok and server_status and server_status != choice:
        detail = f"server status: {server_status}"
    return {
        "request_id": _clean_id(request_id),
        "decision": choice,
        "outcome": outcome,
        "status": server_status,
        "failure_type": _redact_text(failure_type, 80),
        "detail": detail,
    }


def bulk_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-item bulk results for partial-failure reporting."""
    succeeded = 0
    failed = 0
    failed_ids: List[str] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("outcome") == "succeeded":
            succeeded += 1
        else:
            failed += 1
            request_id = _clean_id(row.get("request_id"))
            if request_id:
                failed_ids.append(request_id)
    return {
        "total": succeeded + failed,
        "succeeded": succeeded,
        "failed": failed,
        "failed_ids": failed_ids,
    }


def _export_row(
    record: Mapping[str, Any],
    now: Optional[float],
    warning_hours: float,
    critical_hours: float,
) -> Dict[str, Any]:
    policy = record.get("policy") if isinstance(record.get("policy"), Mapping) else {}
    created = _as_number(record.get("created_at"))
    age = age_seconds(record, now)
    evidence = evidence_links(record)
    return {
        "request_id": _clean_id(record.get("request_id")),
        "status": _redact_text(record.get("status"), 40),
        "action": _redact_text(record.get("action"), 80),
        "reason": _redact_text(record.get("reason"), 300),
        "policy": policy_summary(policy),
        "requester": requester_value(record),
        "tenant": tenant_value(record),
        "workspace": workspace_value(record),
        "app": app_value(record),
        "created_at": created,
        "created_at_utc": _utc_iso(created),
        "age_seconds": int(age) if age is not None else None,
        "sla": sla_label(sla_bucket(record, now, warning_hours, critical_hours)),
        "decided_at": _as_number(record.get("decided_at")),
        "decided_at_utc": _utc_iso(record.get("decided_at")),
        "decided_by": _redact_text(record.get("decided_by"), 120),
        "decision_note": _redact_text(record.get("decision_note"), 1000),
        "evidence_ids": "; ".join(
            f"{item['kind']}={item['value']}" for item in evidence
        ),
    }


def export_rows(
    records: Sequence[Mapping[str, Any]],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> List[Dict[str, Any]]:
    """Build safe metadata export rows; raw approval context is never included."""
    moment = float(now) if now is not None else time.time()
    return [
        _export_row(record, moment, warning_hours, critical_hours)
        for record in records or []
        if isinstance(record, Mapping)
    ]


def export_json(
    records: Sequence[Mapping[str, Any]],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> str:
    """Export safe approval metadata as deterministic JSON."""
    moment = float(now) if now is not None else time.time()
    rows = export_rows(records, moment, warning_hours, critical_hours)
    payload = {
        "generated_at": _utc_iso(moment),
        "count": len(rows),
        "approvals": rows,
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + text
    return text


def export_csv(
    records: Sequence[Mapping[str, Any]],
    now: Optional[float] = None,
    warning_hours: float = DEFAULT_SLA_WARNING_HOURS,
    critical_hours: float = DEFAULT_SLA_CRITICAL_HOURS,
) -> str:
    """Export safe approval metadata as spreadsheet-safe CSV."""
    rows = export_rows(records, now, warning_hours, critical_hours)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(SAFE_EXPORT_FIELDS),
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key)) for key in SAFE_EXPORT_FIELDS})
    return buffer.getvalue()


def export_filename(
    suffix: str = "json",
    now: Optional[float] = None,
    prefix: str = "approvals",
) -> str:
    """Stable, filesystem-safe download filename."""
    moment = float(now) if now is not None else time.time()
    stamp = datetime.fromtimestamp(moment, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_prefix = _ID_RE.sub("-", str(prefix or "approvals")).strip("-") or "approvals"
    safe_suffix = _ID_RE.sub("", str(suffix or "json")) or "json"
    return f"{safe_prefix}-{stamp}.{safe_suffix}"


def _collect_evidence(
    value: Any, source: str, prefix: str, rows: List[Dict[str, Any]], seen: set
) -> None:
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        name = str(key)
        path = f"{prefix}.{name}" if prefix else name
        lowered = name.lower()
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            if lowered in _EVIDENCE_KEYS or lowered.endswith(("_request_id", "_trace_id")):
                cleaned = _clean_id(item)
                fingerprint = (lowered, cleaned)
                if cleaned and fingerprint not in seen:
                    seen.add(fingerprint)
                    rows.append({"kind": lowered, "value": cleaned, "source": source})
        elif isinstance(item, Mapping):
            _collect_evidence(item, source, path, rows, seen)
        elif isinstance(item, (list, tuple)):
            for element in item:
                _collect_evidence(element, source, path, rows, seen)


def evidence_links(record: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Extract copyable trace/run/audit correlation ids from context/policy."""
    rows: List[Dict[str, str]] = []
    seen: set = set()
    for source in ("context", "policy"):
        _collect_evidence(record.get(source), source, "", rows, seen)
    return rows[:20]


def can_decide(record: Optional[Mapping[str, Any]]) -> bool:
    """Only pending requests can receive a decision."""
    if record is None:
        return False
    return record.get("status") == "pending"


def decision_payload(
    decision: str, decided_by: Optional[str] = None, note: Optional[str] = None
) -> Dict[str, str]:
    """Build the decision body, validating the choice before calling the API."""
    choice = str(decision or "").strip().lower()
    if choice not in DECISIONS:
        raise ValueError("Decision must be 'approved' or 'rejected'")
    payload: Dict[str, str] = {"decision": choice}
    reviewer = _redact_text(decided_by, 120)
    if reviewer:
        payload["decided_by"] = reviewer
    comment = _redact_text(note, 1000)
    if comment:
        payload["note"] = comment
    return payload


def deep_link_params(request_id: Any) -> Dict[str, str]:
    """Workspace-compatible direct params for a selected approval (#151)."""
    cleaned = _clean_id(request_id)
    if not cleaned:
        return {}
    return {"screen": "Approvals", "approval_request": cleaned}
