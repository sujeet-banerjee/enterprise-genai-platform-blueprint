"""Traces timeline/waterfall helpers (issue #133).

Pure helpers to build a timeline from observability latency/stages and
trace payloads; redaction-safe and Streamlit-free.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ui.components import (
    badge_markdown,
    badge_model,
    format_cost_usd,
    format_count,
    format_duration_ms,
    key_value_markdown,
    kpi_model,
    kpi_strip_markdown,
    section_card_markdown,
    section_card_model,
)

STAGE_ORDER = [
    "input_redaction",
    "guardrail_input",
    "query_validation",
    "embedding",
    "retrieval",
    "reranking",
    "query_expansion",
    "token_budget",
    "prompt_build",
    "llm_generation",
    "guardrail_output",
    "evaluation",
]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def build_timeline(item: Mapping[str, Any]) -> List[Dict[str, Any]]:
    latency = item.get("latency") or {}
    stages = latency.get("stages") or {}
    rows = []
    total = _num(latency.get("total_ms")) or 0.0
    order = list(STAGE_ORDER)
    # include any extra stages in sorted order after known
    for k in stages.keys():
        if k not in order:
            order.append(k)
    for stage in order:
        info = stages.get(stage)
        if not isinstance(info, Mapping):
            continue
        ms = _num(info.get("ms")) or 0.0
        if ms == 0.0 and stage not in stages:
            continue
        pct = round((ms / total * 100.0), 1) if total > 0 else 0.0
        rows.append({"stage": stage, "ms": ms, "pct": pct, "count": info.get("count")})
    if not rows and total > 0:
        rows.append({"stage": "total", "ms": total, "pct": 100.0, "count": None})
    return rows


def build_waterfall(item: Mapping[str, Any], bar_width: int = 28) -> List[Dict[str, Any]]:
    latency = item.get("latency") or {}
    if not isinstance(latency, Mapping):
        latency = {}
    stages = latency.get("stages") or {}
    if not isinstance(stages, Mapping):
        stages = {}
    stage_ms = {
        str(name): _num(info.get("ms"))
        for name, info in stages.items()
        if isinstance(info, Mapping) and _num(info.get("ms")) is not None
    }
    total = _num(latency.get("total_ms")) or sum(value or 0.0 for value in stage_ms.values())
    order = list(STAGE_ORDER) + sorted(name for name in stage_ms if name not in STAGE_ORDER)
    rows: List[Dict[str, Any]] = []
    cursor = 0.0
    for stage in order:
        if stage not in stage_ms:
            continue
        duration = max(0.0, float(stage_ms[stage] or 0.0))
        start = cursor
        end = cursor + duration
        cursor = end
        pct = round(duration / total * 100.0, 1) if total > 0 else 0.0
        filled = min(bar_width, int(round(duration / total * bar_width))) if duration and total else 0
        rows.append(
            {
                "stage": stage,
                "start_ms": round(start, 3),
                "end_ms": round(end, 3),
                "duration_ms": round(duration, 3),
                "pct": pct,
                "count": stages.get(stage, {}).get("count") if isinstance(stages.get(stage), Mapping) else None,
                "bar": "[" + ("#" * filled) + ("." * (bar_width - filled)) + "]",
            }
        )
    if not rows and total > 0:
        rows.append(
            {
                "stage": "total",
                "start_ms": 0.0,
                "end_ms": round(total, 3),
                "duration_ms": round(total, 3),
                "pct": 100.0,
                "count": None,
                "bar": "[" + ("#" * bar_width) + "]",
            }
        )
    return rows


def waterfall_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-card genai-muted">No stage latency recorded.</div>'
    parts = [
        '<table class="genai-waterfall-table"><thead><tr><th>Stage</th><th>Start</th>'
        "<th>Duration</th><th>Share</th><th>Span</th><th>Bar</th></tr></thead><tbody>"
    ]
    for row in rows:
        raw_pct = _num(row.get("pct")) or 0.0
        pct = min(100.0, max(0.0, raw_pct))
        parts.append(
            "<tr>"
            f'<td class="genai-waterfall-stage">{escape(str(row.get("stage") or "-"))}</td>'
            f'<td>{escape(format_duration_ms(row.get("start_ms"), "-"))}</td>'
            f'<td>{escape(format_duration_ms(row.get("duration_ms"), "-"))}</td>'
            f'<td>{pct:.1f}%</td>'
            '<td><div class="genai-waterfall-track">'
            f'<span class="genai-waterfall-fill" style="width: {pct:.1f}%"></span>'
            "</div></td>"
            f'<td><code>{escape(str(row.get("bar") or ""))}</code></td>'
            "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)


def trace_summary_view(trace: Mapping[str, Any]) -> Dict[str, Any]:
    latency = trace.get("latency") or {}
    if not isinstance(latency, Mapping):
        latency = {}
    cost = trace.get("cost") or {}
    attribution = trace.get("attribution") or {}
    if not isinstance(attribution, Mapping):
        attribution = {}
    observability = trace.get("observability") or {}
    if not isinstance(observability, Mapping):
        observability = {}
    otel = observability.get("otel") or (trace.get("otel") or {})
    if not isinstance(otel, Mapping):
        otel = {}
    decisions = trace.get("guardrail_decisions") or []
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        decisions = []
    blocks = sum(
        1
        for decision in decisions
        if isinstance(decision, Mapping)
        and str(decision.get("decision") or "").lower() == "block"
    )
    redactions = sum(
        1
        for decision in decisions
        if isinstance(decision, Mapping)
        and str(decision.get("decision") or "").lower() == "redact"
    )
    document_count = 0
    for key in ("retrieved_documents", "final_document_ordering", "initial_retrieved_documents"):
        value = trace.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            document_count = len(value)
            break
    failure_tags = trace.get("failure_tags") or []
    if not isinstance(failure_tags, Sequence) or isinstance(failure_tags, (str, bytes)):
        failure_tags = []
    status = str(trace.get("status") or ("degraded" if failure_tags else "success"))
    direct_cost = _num(trace.get("cost_usd"))
    estimated_cost = _num(cost.get("estimated_cost_usd")) if isinstance(cost, Mapping) else None
    return {
        "request_id": str(observability.get("request_id") or trace.get("request_id") or ""),
        "status": status,
        "failure_type": str(trace.get("failure_type") or ""),
        "failure_tags": ", ".join(str(tag) for tag in failure_tags),
        "tenant": str(trace.get("tenant") or ""),
        "workspace": str(trace.get("workspace") or ""),
        "app": str(trace.get("app") or ""),
        "user": str(attribution.get("user") or ""),
        "total_ms": _num(latency.get("total_ms")),
        "cost_usd": direct_cost if direct_cost is not None else estimated_cost,
        "documents": document_count,
        "guardrail_total": len(decisions),
        "guardrail_blocks": blocks,
        "guardrail_redactions": redactions,
        "cache_hit": bool(trace.get("cache_hit")),
        "otel_trace_id": str(otel.get("trace_id") or ""),
        "otel_span_id": str(otel.get("span_id") or ""),
    }


def summary_badges(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    status = str(summary.get("status") or "unknown").lower()
    failure_type = str(summary.get("failure_type") or "")
    if failure_type or "fail" in status or "block" in status:
        outcome = badge_model("blocked", "Failed")
    elif "degrad" in status or "warn" in status:
        outcome = badge_model("warning", "Degraded")
    else:
        outcome = badge_model("success", "Success")
    badges = [outcome]
    badges.append(
        badge_model("success" if summary.get("cache_hit") else "neutral",
                    "Cache hit" if summary.get("cache_hit") else "Cache miss")
    )
    blocks = int(summary.get("guardrail_blocks") or 0)
    redactions = int(summary.get("guardrail_redactions") or 0)
    if blocks:
        badges.append(badge_model("blocked", f"{blocks} blocked"))
    elif redactions:
        badges.append(badge_model("warning", f"{redactions} redacted"))
    else:
        badges.append(badge_model("neutral", "No guardrail hits"))
    tenant = str(summary.get("tenant") or "")
    if tenant:
        badges.append(badge_model("neutral", f"tenant: {tenant}"))
    if summary.get("otel_trace_id"):
        badges.append(badge_model("neutral", "OTel linked"))
    return badges


def summary_card_markdown(trace: Mapping[str, Any]) -> str:
    summary = trace_summary_view(trace)
    badges = summary_badges(summary)
    badges_html = '<div class="genai-query-badges">' + "".join(
        badge_markdown(badge) for badge in badges
    ) + "</div>"
    kpis = kpi_strip_markdown(
        [
            kpi_model("Outcome", summary["status"]),
            kpi_model("Latency", format_duration_ms(summary["total_ms"])),
            kpi_model("Cost", format_cost_usd(summary["cost_usd"])),
            kpi_model("Documents", format_count(summary["documents"])),
        ]
    )
    details = key_value_markdown(
        [
            {"label": "Request id", "value": summary["request_id"] or "-", "sensitive": False},
            {"label": "Tenant", "value": summary["tenant"] or "-", "sensitive": False},
            {"label": "Workspace", "value": summary["workspace"] or "-", "sensitive": False},
            {"label": "App", "value": summary["app"] or "-", "sensitive": False},
            {"label": "Failure type", "value": summary["failure_type"] or "-", "sensitive": False},
            {"label": "Failure tags", "value": summary["failure_tags"] or "-", "sensitive": False},
        ]
    )
    description = f"{summary['request_id'] or 'request'} · {summary['status']}"
    return section_card_markdown(
        section_card_model("Request summary", description, badges_html + kpis + details)
    )


def _diff_tone(row: Mapping[str, Any]) -> str:
    metric = str(row.get("metric") or "").lower()
    delta = _num(row.get("delta"))
    if delta is None:
        if str(row.get("change") or "") != "changed":
            return "neutral"
        left = str(row.get("left") or "").lower()
        right = str(row.get("right") or "").lower()
        right_positive = right in {"true", "yes", "1"}
        left_positive = left in {"true", "yes", "1"}
        if (
            "cache" in metric
            or "success" in metric
            or "hit" in metric
            or "score" in metric
            or "precision" in metric
            or "recall" in metric
        ):
            if right_positive and not left_positive:
                return "better"
            if left_positive and not right_positive:
                return "worse"
        if (
            "failure" in metric
            or "block" in metric
            or "guardrail" in metric
            or "attempt" in metric
        ):
            if right_positive and not left_positive:
                return "worse"
            if left_positive and not right_positive:
                return "better"
        return "changed"
    if delta == 0:
        return "neutral"
    if "failure" in metric or "block" in metric or "guardrail" in metric or "attempt" in metric:
        return "worse" if delta > 0 else "better"
    if "cache" in metric or "success" in metric:
        return "better" if delta > 0 else "worse"
    return "worse" if delta > 0 else "better"


def compare_highlight_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-card genai-muted">No differing trace metrics.</div>'
    parts = [
        '<table class="genai-diff-table"><thead><tr><th>Metric</th><th>Request A</th>'
        "<th>Request B</th><th>Delta</th></tr></thead><tbody>"
    ]
    for row in rows:
        tone = _diff_tone(row)
        parts.append(
            "<tr>"
            f'<td>{escape(str(row.get("metric") or "-"))}</td>'
            f'<td>{escape(str(row.get("left") if row.get("left") is not None else "-"))}</td>'
            f'<td>{escape(str(row.get("right") if row.get("right") is not None else "-"))}</td>'
            f'<td class="genai-delta genai-delta-{tone}">{escape(str(row.get("delta") if row.get("delta") != "" else "-"))}</td>'
            "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)


def span_filters(timeline: List[Mapping[str, Any]]) -> List[str]:
    return [str(r.get("stage")) for r in timeline if r.get("stage")]


def trace_context(item: Mapping[str, Any]) -> Dict[str, Any]:
    obs = item.get("observability") or {}
    otel = obs.get("otel") or {}
    ctx = {}
    if otel.get("trace_id"):
        ctx["trace_id"] = otel["trace_id"]
    if otel.get("span_id"):
        ctx["span_id"] = otel["span_id"]
    if obs.get("request_id") or item.get("request_id"):
        ctx["request_id"] = obs.get("request_id") or item.get("request_id")
    return ctx


def redaction_safe_view(trace: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy with obvious secret-like keys removed (defensive)."""
    out = {}
    for k, v in trace.items():
        kl = str(k).lower()
        if "key" in kl or "secret" in kl or "token" in kl:
            out[k] = "[REDACTED]"
            continue
        if isinstance(v, Mapping):
            out[k] = redaction_safe_view(v)
        elif isinstance(v, list):
            out[k] = [redaction_safe_view(x) if isinstance(x, Mapping) else x for x in v]
        else:
            out[k] = v
    return out
