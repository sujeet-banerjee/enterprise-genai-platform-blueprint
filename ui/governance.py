"""Governance & metrics UX helpers (issue #134).

Pure helpers for filtering, time windows, export (CSV/JSON) and alerts preview.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Mapping


def time_windows() -> List[str]:
    return ["Last hour", "Last 24h", "Last 7 days", "All"]


def filter_metrics(metrics: Mapping[str, Any], tenant: str = "", app: str = "", user: str = "") -> Dict[str, Any]:
    out = dict(metrics)
    # API already scopes; UI filters are UI-side hints/annotations
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


def alerts_preview(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    alerts = []
    totals = metrics.get("totals") or {}
    failures = _num(totals.get("failures"))
    requests = _num(totals.get("requests"))
    if failures and requests and failures / max(requests, 1) > 0.1:
        alerts.append({"level": "warning", "name": "HighFailureRate", "message": "Failure rate > 10%"})
    guardrails = metrics.get("guardrails") or {}
    blocks = guardrails.get("total_blocks") or 0
    if _num(blocks) and _num(blocks) > 10:
        alerts.append({"level": "info", "name": "GuardrailBlocks", "message": f"{blocks} guardrail blocks observed"})
    return alerts


def _num(v: Any):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)
