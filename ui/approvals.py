"""Pure helpers for the HITL approvals console (issue #163).

This module deliberately has no Streamlit or backend imports. It normalizes the
approval API payloads, redacts secrets before the UI can render them and builds
copyable evidence/deep-link hooks without implementing cross-screen navigation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

STATUS_OPTIONS = ("pending", "approved", "rejected", "all")
DEFAULT_STATUS = "pending"
DECISIONS = ("approved", "rejected")

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


def policy_summary(policy: Any) -> str:
    """Summarize policy id/bundle/action/labels for the queue table."""
    if not isinstance(policy, Mapping):
        return ""
    parts: List[str] = []
    for key in ("policy_id", "bundle", "action"):
        value = policy.get(key)
        if value:
            parts.append(f"{key}={_redact_text(value, 80)}")
    labels = policy.get("labels")
    if labels:
        parts.append("labels=" + ",".join(_redact_text(item, 60) for item in labels))
    return " | ".join(parts)


def approval_rows(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Build bounded, redacted queue rows from ``GET /v1/approvals``."""
    rows: List[Dict[str, Any]] = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        rows.append(
            {
                "request_id": _clean_id(record.get("request_id")),
                "status": _redact_text(record.get("status"), 40),
                "action": _redact_text(record.get("action"), 80),
                "reason": _redact_text(record.get("reason"), 200),
                "policy": policy_summary(record.get("policy")),
                "created": format_timestamp(record.get("created_at")),
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
        status = str(record.get("status") or "").strip().lower()
        if status in ("pending", "approved", "rejected"):
            counts[status] += 1
        else:
            counts["other"] += 1
    return counts


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
