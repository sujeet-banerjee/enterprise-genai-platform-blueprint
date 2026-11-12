"""Cross-object evidence helpers (issue #154).

Pure, Streamlit-free helpers used by the console to move between the trace,
audit, metrics and governance views for the same request, diff two requests
side by side and assemble a redacted evidence pack. The module never imports
``app.*`` or ``core.*`` (HTTP-only rule enforced by ``tests/test_ui_console.py``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ui.traces import STAGE_ORDER, build_timeline

TRACE_SCREEN = "Traces"
AUDIT_SCREEN = "Audit"
GOVERNANCE_SCREEN = "Governance & Cost"

MAX_REQUEST_ID_CHARS = 200
MAX_REQUEST_IDS = 10
MAX_PACK_EVENTS = 50
MAX_PACK_TIMELINE = 40

METRICS_SECTIONS = ("totals", "failures_by_type", "failures_by_tag", "guardrails", "cost")
GOVERNANCE_KEYS = ("enabled", "max_cost_per_request_usd", "safety_margin_tokens", "window")
_SECRET_KEY_SUFFIXES = ("api_key", "apikey", "secret", "password", "_token", "credential")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+=-]*$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*"
    r'|"?(?:api[_-]?key|secret|token|password)"?\s*[:=]\s*"?[^\s,;"]+)',
    re.IGNORECASE,
)


def clean_request_id(value: Any) -> str:
    """Normalise a user-supplied request id (control chars stripped, bounded)."""
    if value is None:
        return ""
    text = _CONTROL_RE.sub("", str(value)).strip().strip("\"'").strip()
    return text[:MAX_REQUEST_ID_CHARS]


def validate_request_id(value: Any) -> str:
    """Return an empty string when valid, else a short human-readable error."""
    rid = clean_request_id(value)
    if not rid:
        return "Request id is required."
    if not _REQUEST_ID_RE.match(rid):
        return "Request id contains unsupported characters (use letters, digits and ._ : @ / + = -)."
    return ""


def parse_request_ids(text: Any) -> List[str]:
    """Split a free-form string into unique request ids, preserving order."""
    raw = _CONTROL_RE.sub("", str(text or ""))
    parts = re.split(r"[\s,;]+", raw)
    seen: List[str] = []
    for part in parts:
        rid = clean_request_id(part)
        if rid and rid not in seen:
            seen.append(rid)
        if len(seen) >= MAX_REQUEST_IDS:
            break
    return seen


def lookup_links(request_id: str) -> List[Dict[str, str]]:
    """Cross-object navigation targets for one request (order matters)."""
    rid = clean_request_id(request_id)
    if not rid:
        return []
    return [
        {
            "target": "trace",
            "label": "Open trace",
            "screen": TRACE_SCREEN,
            "help": "Trace timeline, guardrails and resilience for this request.",
        },
        {
            "target": "audit",
            "label": "Open audit",
            "screen": AUDIT_SCREEN,
            "help": "Audit events recorded for this request id.",
        },
        {
            "target": "metrics",
            "label": "Open metrics",
            "screen": GOVERNANCE_SCREEN,
            "help": "Aggregate metrics for the current tenant scope.",
        },
        {
            "target": "governance",
            "label": "Open governance",
            "screen": GOVERNANCE_SCREEN,
            "help": "Governance caps and the rolling spend window.",
        },
    ]


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def stage_map(trace: Mapping[str, Any]) -> Dict[str, float]:
    """Per-stage latency in milliseconds from a trace payload."""
    latency = trace.get("latency") or {}
    stages = latency.get("stages") or {}
    out: Dict[str, float] = {}
    if not isinstance(stages, Mapping):
        return out
    for name, info in stages.items():
        if isinstance(info, Mapping):
            ms = _num(info.get("ms"))
            if ms is not None:
                out[str(name)] = ms
    return out


def document_count(trace: Mapping[str, Any]) -> int:
    """Number of retrieved documents recorded on the trace."""
    for key in ("retrieved_documents", "final_document_ordering", "initial_retrieved_documents"):
        value = trace.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return len(value)
    return 0


def guardrail_counts(trace: Mapping[str, Any]) -> Dict[str, int]:
    decisions = trace.get("guardrail_decisions") or []
    total = blocks = redactions = 0
    for decision in decisions if isinstance(decisions, Sequence) else []:
        if not isinstance(decision, Mapping):
            continue
        total += 1
        kind = str(decision.get("decision") or "").lower()
        if kind == "block":
            blocks += 1
        elif kind == "redact":
            redactions += 1
    return {"total": total, "blocks": blocks, "redactions": redactions}


def guardrail_signature(trace: Mapping[str, Any]) -> str:
    decisions = trace.get("guardrail_decisions") or []
    parts = []
    for decision in decisions if isinstance(decisions, Sequence) else []:
        if isinstance(decision, Mapping):
            name = str(decision.get("guardrail") or "?")
            kind = str(decision.get("decision") or "?")
            parts.append(f"{name}:{kind}")
    return ", ".join(parts)


def cost_value(trace: Mapping[str, Any]) -> Optional[float]:
    """Per-request cost when the trace carries it (older traces do not)."""
    direct = _num(trace.get("cost_usd"))
    if direct is not None:
        return direct
    cost = trace.get("cost")
    if isinstance(cost, Mapping):
        return _num(cost.get("estimated_cost_usd"))
    return None


def scope_of(trace: Mapping[str, Any]) -> Dict[str, str]:
    attribution = trace.get("attribution") or {}
    return {
        "tenant": str(trace.get("tenant") or ""),
        "workspace": str(trace.get("workspace") or ""),
        "app": str(trace.get("app") or ""),
        "user": str(attribution.get("user") or "") if isinstance(attribution, Mapping) else "",
    }


def cross_scope_notice(trace: Mapping[str, Any], tenant: str) -> str:
    """Warn when a trace belongs to another tenant than the caller's scope."""
    owner = scope_of(trace).get("tenant", "")
    if owner and tenant and owner != tenant:
        return (
            f"This trace belongs to tenant '{owner}', not your current scope '{tenant}'. "
            "Evidence links are disabled for cross-tenant traces."
        )
    return ""


def trace_summary(trace: Mapping[str, Any]) -> Dict[str, Any]:
    """Flat, display-safe summary of the fields evidence workflows compare."""
    latency = trace.get("latency") or {}
    budget = trace.get("token_budget") or {}
    resilience = trace.get("resilience") or {}
    counts = guardrail_counts(trace)
    scope = scope_of(trace)
    return {
        "request_id": str(trace.get("request_id") or ""),
        "status": str(
            trace.get("status")
            or ("degraded" if trace.get("failure_tags") else "success")
        ),
        "failure_type": str(trace.get("failure_type") or ""),
        "failure_tags": ", ".join(str(tag) for tag in (trace.get("failure_tags") or [])),
        "tenant": scope["tenant"],
        "workspace": scope["workspace"],
        "app": scope["app"],
        "user": scope["user"],
        "total_ms": _num(latency.get("total_ms")),
        "documents": document_count(trace),
        "top_k": _num(trace.get("top_k")),
        "guardrail_total": counts["total"],
        "guardrail_blocks": counts["blocks"],
        "guardrail_redactions": counts["redactions"],
        "guardrail_signature": guardrail_signature(trace),
        "cache_hit": bool(trace.get("cache_hit")),
        "input_tokens": _num(budget.get("input_tokens_estimated")),
        "allowed_output_tokens": _num(budget.get("allowed_output_tokens")),
        "cost_usd": cost_value(trace),
        "resilience_attempts": _num(resilience.get("attempts")),
        "resilience_failovers": _num(resilience.get("failovers")),
        "resilience_breaker_opens": _num(resilience.get("breaker_opens")),
        "resilience_served_by": str(resilience.get("served_by") or ""),
        "resilience_tags": ", ".join(str(tag) for tag in (resilience.get("tags") or [])),
        "otel_trace_id": str((trace.get("otel") or {}).get("trace_id") or ""),
    }


def _comparable(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return value


def _same(left: Any, right: Any) -> bool:
    return _comparable(left) == _comparable(right)


def _row(
    metric: str,
    left: Any,
    right: Any,
    *,
    numeric: bool = False,
    highlight: bool = True,
) -> Dict[str, Any]:
    delta: Any = ""
    if numeric and isinstance(left, (int, float)) and isinstance(right, (int, float)):
        delta = round(float(right) - float(left), 3)
    change = "same" if _same(left, right) else "changed"
    return {
        "metric": metric,
        "left": left,
        "right": right,
        "delta": delta,
        "change": change,
        "highlight": bool(highlight and change == "changed"),
    }


def diff_traces(left: Mapping[str, Any], right: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Row-by-row comparison of two traces (latency, failures, docs, guardrails)."""
    ls = trace_summary(left)
    rs = trace_summary(right)
    rows: List[Dict[str, Any]] = [
        _row("status", ls["status"], rs["status"]),
        _row("failure type", ls["failure_type"], rs["failure_type"]),
        _row("failure tags", ls["failure_tags"], rs["failure_tags"]),
        _row("total latency (ms)", ls["total_ms"], rs["total_ms"], numeric=True),
    ]

    left_stages = stage_map(left)
    right_stages = stage_map(right)
    order = list(STAGE_ORDER) + sorted(
        name for name in {*left_stages, *right_stages} if name not in STAGE_ORDER
    )
    for stage in order:
        if stage not in left_stages and stage not in right_stages:
            continue
        rows.append(
            _row(
                f"stage latency: {stage} (ms)",
                left_stages.get(stage, 0.0),
                right_stages.get(stage, 0.0),
                numeric=True,
            )
        )

    rows.extend(
        [
            _row("documents retrieved", ls["documents"], rs["documents"], numeric=True),
            _row("top_k", ls["top_k"], rs["top_k"], numeric=True),
            _row(
                "guardrail decisions", ls["guardrail_total"], rs["guardrail_total"], numeric=True
            ),
            _row("guardrail blocks", ls["guardrail_blocks"], rs["guardrail_blocks"], numeric=True),
            _row(
                "guardrail redactions",
                ls["guardrail_redactions"],
                rs["guardrail_redactions"],
                numeric=True,
            ),
            _row("guardrail signature", ls["guardrail_signature"], rs["guardrail_signature"]),
            _row("cache hit", ls["cache_hit"], rs["cache_hit"]),
            _row(
                "resilience attempts",
                ls["resilience_attempts"],
                rs["resilience_attempts"],
                numeric=True,
            ),
            _row(
                "resilience failovers",
                ls["resilience_failovers"],
                rs["resilience_failovers"],
                numeric=True,
            ),
            _row(
                "resilience breaker opens",
                ls["resilience_breaker_opens"],
                rs["resilience_breaker_opens"],
                numeric=True,
            ),
            _row(
                "resilience served by",
                ls["resilience_served_by"],
                rs["resilience_served_by"],
            ),
            _row("resilience tags", ls["resilience_tags"], rs["resilience_tags"]),
            _row(
                "input tokens (est.)",
                ls["input_tokens"],
                rs["input_tokens"],
                numeric=True,
            ),
            _row(
                "allowed output tokens",
                ls["allowed_output_tokens"],
                rs["allowed_output_tokens"],
                numeric=True,
            ),
            _row(
                "cost (USD)",
                ls["cost_usd"] if ls["cost_usd"] is not None else "n/a",
                rs["cost_usd"] if rs["cost_usd"] is not None else "n/a",
                numeric=ls["cost_usd"] is not None and rs["cost_usd"] is not None,
            ),
            _row("tenant", ls["tenant"], rs["tenant"], highlight=False),
            _row("app", ls["app"], rs["app"], highlight=False),
            _row("user", ls["user"], rs["user"], highlight=False),
        ]
    )
    return rows


def changed_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Only the rows flagged as meaningful differences."""
    return [dict(row) for row in rows if row.get("highlight")]


def audit_events_for(
    events: Iterable[Mapping[str, Any]],
    request_id: str,
    limit: int = MAX_PACK_EVENTS,
) -> List[Dict[str, Any]]:
    """Client-side request-id filter over the audit trail (dependency-free)."""
    rid = clean_request_id(request_id)
    if not rid:
        return []
    matches = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("request_id") or "") != rid:
            continue
        matches.append(dict(event))
        if len(matches) >= max(1, int(limit)):
            break
    return matches


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered == "key":
        return True
    return any(lowered.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES)


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            out[name] = "[REDACTED]" if _secret_key(name) else _scrub(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def _subset(data: Optional[Mapping[str, Any]], keys: Sequence[str]) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    return {key: data[key] for key in keys if key in data}


def build_evidence_pack(
    *,
    request_id: str,
    trace: Mapping[str, Any],
    audit_events: Optional[Iterable[Mapping[str, Any]]] = None,
    metrics: Optional[Mapping[str, Any]] = None,
    governance: Optional[Mapping[str, Any]] = None,
    comparison: Optional[Iterable[Mapping[str, Any]]] = None,
    scope: Optional[Mapping[str, Any]] = None,
    generated_at: str = "",
) -> Dict[str, Any]:
    """Assemble a redacted, JSON-ready evidence pack for one request."""
    rid = clean_request_id(request_id) or str(trace.get("request_id") or "")
    pack_scope = {
        "tenant": str((scope or {}).get("tenant") or trace.get("tenant") or ""),
        "workspace": str((scope or {}).get("workspace") or trace.get("workspace") or ""),
    }
    timeline = build_timeline(trace)[:MAX_PACK_TIMELINE]
    pack: Dict[str, Any] = {
        "schema": "genai-evidence-pack/v1",
        "generated_at": generated_at,
        "request_id": rid,
        "scope": pack_scope,
        "summary": trace_summary(trace),
        "timeline": timeline,
        "audit_events": audit_events_for(audit_events or [], rid),
        "metrics": _subset(metrics, METRICS_SECTIONS),
        "governance": _subset(governance, GOVERNANCE_KEYS),
        "comparison": [dict(row) for row in (comparison or [])],
        "redacted": True,
    }
    return _scrub(pack)


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).replace("|", "\\|").replace("\n", " ")


def evidence_pack_markdown(pack: Mapping[str, Any]) -> str:
    """Render an evidence pack as a shareable Markdown document."""
    summary = pack.get("summary") or {}
    lines = [
        f"# Evidence pack: {_cell(pack.get('request_id'))}",
        "",
        f"Generated: {_cell(pack.get('generated_at'))}  ",
        "Scope: tenant="
        f"{_cell((pack.get('scope') or {}).get('tenant'))} "
        f"workspace={_cell((pack.get('scope') or {}).get('workspace'))}",
        "",
        "> Secrets, keys and raw configuration values are redacted.",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for key in (
        "status",
        "failure_type",
        "failure_tags",
        "tenant",
        "app",
        "user",
        "total_ms",
        "documents",
        "guardrail_total",
        "guardrail_blocks",
        "guardrail_redactions",
        "guardrail_signature",
        "cache_hit",
        "input_tokens",
        "allowed_output_tokens",
        "cost_usd",
        "resilience_attempts",
        "resilience_failovers",
        "served_by",
        "otel_trace_id",
    ):
        value = summary.get(key)
        if value in (None, "", []):
            continue
        lines.append(f"| {key} | {_cell(value)} |")

    timeline = pack.get("timeline") or []
    if timeline:
        lines.extend(["", "## Timeline", "", "| Stage | ms | % |", "|---|---|---|"])
        for row in timeline:
            lines.append(
                f"| {_cell(row.get('stage'))} | {_cell(row.get('ms'))} | "
                f"{_cell(row.get('pct'))} |"
            )

    events = pack.get("audit_events") or []
    if events:
        lines.extend(
            [
                "",
                "## Audit events",
                "",
                "| Timestamp | Event | Action | Outcome |",
                "|---|---|---|---|",
            ]
        )
        for event in events:
            lines.append(
                f"| {_cell(event.get('timestamp'))} | {_cell(event.get('event_type'))} | "
                f"{_cell(event.get('action'))} | {_cell(event.get('outcome'))} |"
            )

    comparison = pack.get("comparison") or []
    highlighted = [row for row in comparison if row.get("highlight")]
    if highlighted:
        lines.extend(
            ["", "## Compare with another request", "", "| Metric | Left | Right | Δ |", "|---|---|---|---|"]
        )
        for row in highlighted:
            lines.append(
                f"| {_cell(row.get('metric'))} | {_cell(row.get('left'))} | "
                f"{_cell(row.get('right'))} | {_cell(row.get('delta'))} |"
            )

    metrics = pack.get("metrics") or {}
    totals = metrics.get("totals") if isinstance(metrics, Mapping) else None
    if isinstance(totals, Mapping) and totals:
        lines.extend(["", "## Metrics totals", "", "| Metric | Value |", "|---|---|"])
        for key, value in totals.items():
            lines.append(f"| {_cell(key)} | {_cell(value)} |")

    lines.append("")
    return "\n".join(lines)


def evidence_pack_filename(request_id: str, extension: str = "json") -> str:
    """Stable, filesystem-safe download name."""
    rid = re.sub(r"[^A-Za-z0-9._-]+", "-", clean_request_id(request_id)).strip("-")
    return f"evidence-{rid or 'request'}.{extension.lstrip('.')}"
