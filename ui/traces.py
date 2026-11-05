"""Traces timeline/waterfall helpers (issue #133).

Pure helpers to build a timeline from observability latency/stages and
trace payloads; redaction-safe and Streamlit-free.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

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
