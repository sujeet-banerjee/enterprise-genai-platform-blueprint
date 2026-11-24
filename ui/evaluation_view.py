"""Structured Evaluation presentation helpers (issue #248).

Pure, Streamlit-free view models for sectioned cards, background-job status,
highlighted comparison matrices, and experiment status. No backend imports.
"""

from __future__ import annotations

import math
from html import escape
from typing import Any, Dict, List, Mapping, Sequence

from ui.components import (
    badge_markdown,
    badge_model,
    format_auto,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    kpi_strip_markdown,
    redact_payload,
    section_card_markdown,
    section_card_model,
)
from ui.evaluation import METRIC_EXPLANATIONS, build_comparison_matrix

__all__ = [
    "comparison_chart_data",
    "comparison_matrix_markdown",
    "comparison_matrix_rows",
    "evaluation_section_cards",
    "experiment_status_view",
    "job_status_markdown",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _truncate(value: str, limit: int = 160) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _find_key(node: Any, key: str, depth: int = 0) -> Any:
    if not isinstance(node, Mapping) or depth > 6:
        return None
    if key in node:
        return node[key]
    for value in node.values():
        if isinstance(value, Mapping):
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
        elif isinstance(value, (list, tuple)):
            for item in value:
                found = _find_key(item, key, depth + 1)
                if found is not None:
                    return found
    return None


def _metric_text(metrics: Any) -> str:
    if not isinstance(metrics, Mapping) or not metrics:
        return "-"
    return ", ".join(
        f"{key}={format_auto(value)}" for key, value in metrics.items()
    )


def evaluation_section_cards(
    dataset: Any = None,
    run: Any = None,
    results: Any = None,
) -> Dict[str, str]:
    """Return dataset/run/results section cards as escaped HTML fragments."""
    dataset_data = dataset if isinstance(dataset, Mapping) else {}
    run_data = run if isinstance(run, Mapping) else {}
    results_data = results if isinstance(results, Mapping) else {}

    dataset_rows = key_value_rows(
        dataset_data,
        labels={
            "label": "Dataset",
            "description": "Description",
            "docs_count": "Documents",
            "cases_count": "Cases",
            "source": "Source",
        },
    )
    run_rows = key_value_rows(
        run_data,
        labels={
            "evaluator": "Evaluator",
            "query": "Query",
            "ground_truth": "Ground truth",
            "top_k": "Top k",
            "dataset_source": "Dataset source",
        },
    )
    result_payload: Dict[str, Any] = {}
    if results_data:
        result_payload = {
            "evaluator": results_data.get("evaluator"),
            "docs_source": results_data.get("docs_source"),
            "num_retrieved_docs": results_data.get("num_retrieved_docs"),
            "ground_truth_used": results_data.get("ground_truth_used"),
            "metrics": _metric_text(results_data.get("metrics")),
        }
    result_rows = key_value_rows(
        result_payload,
        labels={
            "evaluator": "Evaluator",
            "docs_source": "Context source",
            "num_retrieved_docs": "Retrieved docs",
            "ground_truth_used": "Ground truth used",
            "metrics": "Metrics",
        },
    )
    return {
        "dataset": section_card_markdown(
            section_card_model(
                "Dataset",
                "Selected evaluation source",
                key_value_markdown(dataset_rows),
            )
        ),
        "run": section_card_markdown(
            section_card_model(
                "Run",
                "Single query evaluation setup",
                key_value_markdown(run_rows),
            )
        ),
        "results": section_card_markdown(
            section_card_model(
                "Results",
                "Evaluator output and metric summary",
                key_value_markdown(result_rows),
            )
        ),
    }


def job_status_markdown(snapshot: Any) -> str:
    """Return a status badge plus case counter KPIs for a background job."""
    data = snapshot if isinstance(snapshot, Mapping) else {}
    status = _text(data.get("status")) or "unknown"
    badge = badge_model(status, label=status.replace("_", " ").title())
    total = data.get("total", 0)
    done = data.get("done", 0)
    kpis = kpi_strip(
        [
            {"label": "Cases", "value": f"{done} / {total}"},
            {"label": "Succeeded", "value": data.get("succeeded", 0)},
            {"label": "Failed", "value": data.get("failed", 0)},
        ]
    )
    body = badge_markdown(badge) + kpi_strip_markdown(kpis)
    return section_card_markdown(
        section_card_model(
            "Background job",
            _truncate(
                f"{_text(data.get('label')) or 'dataset'} | "
                f"job {_text(data.get('job_id')) or '-'}"
            ),
            body,
        )
    )


def comparison_matrix_rows(runs: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten runs into matrix rows and mark the best numeric metric per column."""
    matrix = build_comparison_matrix(runs)
    metric_keys = [
        metric.key
        for metric in METRIC_EXPLANATIONS
        if any(_is_number(row.get(metric.key)) for row in matrix)
    ]
    best: Dict[str, float] = {}
    for key in metric_keys:
        values = [float(row[key]) for row in matrix if _is_number(row.get(key))]
        if values:
            best[key] = max(values)

    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(matrix, start=1):
        rendered: Dict[str, Any] = {
            "run": _text(row.get("run_id")) or f"Run {index}",
            "evaluator": _text(row.get("evaluator")) or "-",
            "gt_used": format_auto(row.get("gt_used")),
        }
        for key in metric_keys:
            value = row.get(key)
            rendered[key] = value
            rendered[f"{key}__best"] = _is_number(value) and float(value) == best.get(key)
        rows.append(rendered)
    return rows


def comparison_matrix_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render the comparison matrix with best-value highlights."""
    if not rows:
        return '<div class="genai-card genai-muted">No comparison runs yet.</div>'
    metric_keys = [
        key
        for key in rows[0]
        if key not in {"run", "evaluator", "gt_used"} and not key.endswith("__best")
    ]
    labels = {metric.key: metric.label for metric in METRIC_EXPLANATIONS}
    headers = ["Run", "Evaluator", "GT used", *[labels.get(key, key) for key in metric_keys]]
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)

    body_rows: List[str] = []
    for row in rows:
        cells = [
            f"<td>{escape(_truncate(_text(row.get('run')) or '-'))}</td>",
            f"<td>{escape(_truncate(_text(row.get('evaluator')) or '-'))}</td>",
            f"<td>{escape(_text(row.get('gt_used')) or '-')}</td>",
        ]
        for key in metric_keys:
            value = format_auto(row.get(key))
            best = bool(row.get(f"{key}__best"))
            css = ' class="genai-metric-best"' if best else ""
            cells.append(f"<td{css}>{escape(value)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="genai-table-scroll">'
        '<table class="genai-diff-table genai-eval-matrix">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def comparison_chart_data(rows: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    """Average each numeric metric for the comparison bar chart."""
    labels = {metric.key: metric.label for metric in METRIC_EXPLANATIONS}
    chart: Dict[str, float] = {}
    for metric in METRIC_EXPLANATIONS:
        values = [
            float(row[metric.key])
            for row in rows
            if _is_number(row.get(metric.key))
            and math.isfinite(float(row[metric.key]))
        ]
        if values:
            chart[labels.get(metric.key, metric.key)] = round(
                sum(values) / len(values), 6
            )
    return chart


def experiment_status_view(payload: Any) -> Dict[str, Any]:
    """Structured experiment summary plus a redacted raw payload."""
    data = payload if isinstance(payload, Mapping) else {}
    identifier = (
        _find_key(data, "id")
        or _find_key(data, "experiment_id")
        or _find_key(data, "request_id")
        or "-"
    )
    state = _find_key(data, "status") or _find_key(data, "state") or "unknown"
    kind = _find_key(data, "kind") or "-"
    metrics = _find_key(data, "metrics")
    summary = {
        "experiment_id": identifier,
        "state": state,
        "kind": kind,
        "metrics": _metric_text(metrics),
    }
    body = badge_markdown(badge_model(state)) + key_value_markdown(
        key_value_rows(summary)
    )
    return {
        "markdown": section_card_markdown(
            section_card_model(
                "Experiment status",
                "Structured id/state/metrics before the raw response",
                body,
            )
        ),
        "raw": redact_payload(data),
        "summary": summary,
    }
