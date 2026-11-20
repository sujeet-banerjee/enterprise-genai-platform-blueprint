"""Governance & metrics UX helpers (issues #134, #245).

Pure helpers for filtering, time windows, export (CSV/JSON), alerts and
structured governance/cost view models.
"""

from __future__ import annotations

import csv
import io
import json
from html import escape
from typing import Any, Dict, List, Mapping, Optional

from ui.components import (
    alert_markdown,
    alert_model,
    format_cost_usd,
    kpi_model,
)

GUARDRAIL_LEGEND = [
    {"decision": "allow", "label": "Allow", "tone": "success"},
    {"decision": "redact", "label": "Redact", "tone": "warning"},
    {"decision": "block", "label": "Block", "tone": "danger"},
]


def time_windows() -> List[str]:
    return ["Last hour", "Last 24h", "Last 7 days", "All"]


def filter_metrics(metrics: Mapping[str, Any], tenant: str = "", app: str = "", user: str = "") -> Dict[str, Any]:
    out = dict(metrics)
    out["_ui_filters"] = {"tenant": tenant, "app": app, "user": user}
    return out


def metrics_to_csv(metrics: Mapping[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    for section in ("totals", "by_stage", "failures_by_type", "failures_by_tag", "cost_by_model", "guardrails"):
        data = metrics.get(section)
        if isinstance(data, Mapping):
            for k, v in data.items():
                w.writerow([section, k, v])
        elif isinstance(data, List):
            for i, item in enumerate(data):
                if isinstance(item, Mapping):
                    for k, v in item.items():
                        w.writerow([f"{section}[{i}]", k, v])
    return buf.getvalue()


def metrics_to_json(metrics: Mapping[str, Any]) -> str:
    return json.dumps(metrics, indent=2)


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _first_num(*values: Any) -> Optional[float]:
    for value in values:
        number = _num(value)
        if number is not None:
            return number
    return None


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def alerts_preview(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    totals = _mapping(metrics.get("totals"))
    failures = _first_num(totals.get("failures"), metrics.get("failure_count"))
    requests = _first_num(
        totals.get("requests"), metrics.get("total_runs"), metrics.get("total_requests")
    )
    if failures is not None and requests is not None and requests > 0:
        rate = failures / requests
        if rate >= 0.25:
            alerts.append(
                {
                    "level": "critical",
                    "name": "CriticalFailureRate",
                    "message": "Failure rate > 25% in the selected window",
                }
            )
        elif rate > 0.1:
            alerts.append(
                {
                    "level": "warning",
                    "name": "HighFailureRate",
                    "message": "Failure rate > 10% in the selected window",
                }
            )
    guardrails = _mapping(metrics.get("guardrails"))
    blocks = _first_num(guardrails.get("total_blocks"), metrics.get("total_blocks"))
    if blocks is not None and blocks > 10:
        alerts.append(
            {
                "level": "warning",
                "name": "GuardrailBlocks",
                "message": f"{int(blocks)} guardrail blocks observed",
            }
        )
    return alerts


def cost_summary(status: Mapping[str, Any], metrics: Mapping[str, Any]) -> Dict[str, Any]:
    window = _mapping(status.get("window"))
    cost = _mapping(metrics.get("cost"))
    spend = _first_num(window.get("total_cost_usd"), cost.get("total_cost_usd"), 0) or 0.0
    mean = _first_num(window.get("mean_cost_usd"), cost.get("mean_cost_usd"), 0) or 0.0
    requests = _first_num(window.get("requests"), metrics.get("total_runs"), 0) or 0.0
    cap = _first_num(status.get("max_cost_per_request_usd"))
    margin = _first_num(status.get("safety_margin_tokens"))
    return {
        "spend_usd": spend,
        "mean_usd": mean,
        "requests": requests,
        "cap_usd": cap,
        "safety_margin_tokens": margin,
        "enabled": bool(status.get("enabled")),
        "window_size": _first_num(window.get("window_size"), 0) or 0.0,
        "priced_runs": _first_num(cost.get("priced_runs"), 0) or 0.0,
    }


def cost_kpis(status: Mapping[str, Any], metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    summary = cost_summary(status, metrics)
    enabled = summary["enabled"]
    failure_rate = _num(metrics.get("failure_rate")) or 0.0
    guardrails = _mapping(metrics.get("guardrails"))
    blocks = _first_num(guardrails.get("total_blocks"), 0) or 0.0
    return [
        kpi_model("Window spend", format_cost_usd(summary["spend_usd"]), status="success"),
        kpi_model("Mean / request", format_cost_usd(summary["mean_usd"])),
        kpi_model(
            "Policy cap / request",
            format_cost_usd(summary["cap_usd"]) if summary["cap_usd"] is not None else "not set",
        ),
        kpi_model("Requests", int(summary["requests"])),
        kpi_model("Failure rate", f"{failure_rate * 100:.1f}%", status="warning" if failure_rate > 0.1 else None),
        kpi_model("Guardrail blocks", int(blocks), status="danger" if blocks > 0 else None),
        kpi_model("Governance", "enabled" if enabled else "disabled", status="success" if enabled else "neutral"),
    ]


def cost_chart_rows(status: Mapping[str, Any], metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    summary = cost_summary(status, metrics)
    cost = _mapping(metrics.get("cost"))
    by_model = _mapping(cost.get("by_model") or metrics.get("cost_by_model"))
    rows: List[Dict[str, Any]] = []
    if by_model:
        for name, value in sorted(by_model.items(), key=lambda item: str(item[0])):
            amount = _num(value)
            if amount is not None:
                rows.append({"label": str(name), "value": amount, "display": format_cost_usd(amount)})
    if not rows:
        rows = [
            {"label": "Window spend", "value": summary["spend_usd"], "display": format_cost_usd(summary["spend_usd"])},
            {"label": "Mean / request", "value": summary["mean_usd"], "display": format_cost_usd(summary["mean_usd"])},
        ]
        if summary["cap_usd"] is not None:
            rows.append(
                {
                    "label": "Policy cap / request",
                    "value": summary["cap_usd"],
                    "display": format_cost_usd(summary["cap_usd"]),
                }
            )
    peak = max((max(row["value"], 0.0) for row in rows), default=0.0)
    scale = peak if peak > 0 else 1.0
    for row in rows:
        value = max(row["value"], 0.0)
        row["pct"] = round((value / scale) * 100, 1)
    return rows


def cost_chart_markdown(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-muted">No cost data yet.</div>'
    parts = ['<div class="genai-cost-chart">']
    for row in rows:
        label = escape(str(row.get("label") or "-"))
        display = escape(str(row.get("display") or "-"))
        width = max(0.0, min(100.0, float(_num(row.get("pct")) or 0.0)))
        parts.append(
            '<div class="genai-cost-row">'
            f'<span class="genai-cost-label">{label}</span>'
            '<span class="genai-cost-track">'
            f'<span class="genai-cost-fill" style="width:{width:.1f}%"></span>'
            "</span>"
            f'<span class="genai-cost-value">{display}</span>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def alert_banners(status: Mapping[str, Any], metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    alerts = alerts_preview(metrics)
    summary = cost_summary(status, metrics)
    if summary["enabled"] and summary["cap_usd"] is not None and summary["mean_usd"] > summary["cap_usd"]:
        alerts.insert(
            0,
            {
                "level": "critical",
                "name": "CostPerRequestLimit",
                "message": (
                    f"Mean request cost {format_cost_usd(summary['mean_usd'])} exceeds the "
                    f"configured cap {format_cost_usd(summary['cap_usd'])}"
                ),
            },
        )
    banners: List[Dict[str, Any]] = []
    for alert in alerts:
        level = str(alert.get("level") or "info").lower()
        tone = {
            "critical": "danger",
            "danger": "danger",
            "warning": "warning",
            "info": "info",
        }.get(level, "info")
        banners.append(
            alert_model(
                title=alert.get("name") or "Governance alert",
                message=alert.get("message") or "",
                tone=tone,
            )
        )
    return banners


def alert_banner_markdown(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return ""
    return "".join(alert_markdown(alert) for alert in alerts)


def failure_chart_data(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    failures = _mapping(metrics.get("failures_by_type"))
    counts = [(str(name), _num(value)) for name, value in failures.items()]
    numeric = [(name, value) for name, value in counts if value is not None and value > 0]
    numeric.sort(key=lambda item: (-item[1], item[0]))
    total = sum(value for _, value in numeric)
    peak = max((value for _, value in numeric), default=0.0)
    scale = peak if peak > 0 else 1.0
    return [
        {
            "label": name,
            "count": int(value),
            "pct": round((value / total) * 100, 1) if total else 0.0,
            "width": round((value / scale) * 100, 1),
        }
        for name, value in numeric
    ]


def failure_chart_markdown(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-muted">No failures recorded in this window.</div>'
    parts = ['<div class="genai-failure-chart">']
    for row in rows:
        width = max(0.0, min(100.0, float(_num(row.get("width")) or 0.0)))
        parts.append(
            '<div class="genai-failure-row">'
            f'<span class="genai-failure-label">{escape(str(row.get("label") or "-"))}</span>'
            '<span class="genai-failure-track">'
            f'<span class="genai-failure-fill" style="width:{width:.1f}%"></span>'
            "</span>"
            f'<span class="genai-failure-value">{int(row.get("count") or 0)} ({float(row.get("pct") or 0):.1f}%)</span>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def guardrail_chart_data(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    guardrails = _mapping(metrics.get("guardrails"))
    by_guardrail = _mapping(guardrails.get("by_guardrail"))
    rows: List[Dict[str, Any]] = []
    for name, raw_counts in by_guardrail.items():
        counts = _mapping(raw_counts)
        values = {
            decision: max(int(_num(counts.get(decision)) or 0), 0)
            for decision in ("allow", "redact", "block")
        }
        total = sum(values.values())
        if not total:
            continue
        rows.append(
            {
                "label": str(name),
                "allow": values["allow"],
                "redact": values["redact"],
                "block": values["block"],
                "total": total,
                "segments": [
                    {
                        "decision": decision,
                        "count": values[decision],
                        "width": round((values[decision] / total) * 100, 2),
                    }
                    for decision in ("allow", "redact", "block")
                ],
            }
        )
    rows.sort(key=lambda row: (-row["total"], row["label"]))
    return rows


def guardrail_chart_markdown(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-muted">No guardrail decisions recorded in this window.</div>'
    parts = ['<div class="genai-guardrail-chart">']
    for row in rows:
        segments = []
        for segment in row.get("segments") or []:
            decision = str(segment.get("decision") or "")
            count = int(segment.get("count") or 0)
            width = max(0.0, min(100.0, float(_num(segment.get("width")) or 0.0)))
            segments.append(
                f'<span class="genai-guardrail-segment genai-guardrail-{escape(decision)}" '
                f'style="width:{width:.2f}%" title="{escape(decision)}: {count}"></span>'
            )
        parts.append(
            '<div class="genai-guardrail-row">'
            f'<span class="genai-guardrail-label">{escape(str(row.get("label") or "-"))}</span>'
            '<span class="genai-guardrail-track">' + "".join(segments) + "</span>"
            f'<span class="genai-guardrail-value">{int(row.get("total") or 0)}</span>'
            "</div>"
        )
    parts.append("</div>")
    parts.append('<div class="genai-guardrail-legend">')
    for entry in GUARDRAIL_LEGEND:
        parts.append(
            f'<span class="genai-guardrail-legend-item genai-guardrail-{entry["decision"]}">'
            f'{escape(entry["label"])}</span>'
        )
    parts.append("</div>")
    return "".join(parts)


def governance_view_models(status: Mapping[str, Any], metrics: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kpis": cost_kpis(status, metrics),
        "cost_rows": cost_chart_rows(status, metrics),
        "failure_rows": failure_chart_data(metrics),
        "guardrail_rows": guardrail_chart_data(metrics),
        "alerts": alert_banners(status, metrics),
    }
