"""Pure view models for the Compare (what-if) console screen (issue #247).

No Streamlit or backend imports. Helpers consume ``/ready`` and rebuild payloads
and return escaped HTML or plain view models for a thin Streamlit renderer.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ui.components import (
    format_auto,
    key_value_markdown,
    kpi_strip,
    redact_payload,
)

COMPONENT_LABELS = {
    "llm": "LLM",
    "retriever": "Retriever",
    "reranker": "Reranker",
    "evaluator": "Evaluator",
    "query_expander": "Query expander",
}
OVERRIDE_PATHS = {
    "active_model": ("models", "active_model"),
    "active_embedding_model": ("models", "active_embedding_model"),
    "default_retriever": ("retrieval", "default_retriever"),
    "similarity_metric": ("retrieval", "similarity_metric"),
    "top_k": ("retrieval", "top_k"),
}
TONES = ("better", "worse", "neutral")

__all__ = [
    "COMPONENT_LABELS",
    "OVERRIDE_PATHS",
    "TONES",
    "compare_view_models",
    "component_cards_markdown",
    "component_delta_rows",
    "component_rows",
    "delta_table_markdown",
    "diff_tone",
    "override_delta_rows",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _short(value: str, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _missing(value: Any) -> bool:
    return value is None or not _text(value)


def _display(value: Any, limit: int = 160) -> str:
    safe = redact_payload(value)
    if isinstance(safe, Mapping) or isinstance(safe, (list, tuple, set)):
        rendered = json.dumps(safe, sort_keys=True, default=str)
    else:
        rendered = format_auto(safe)
    return _short(rendered or "-", limit)


def _normalized(value: Any) -> str:
    return "" if _missing(value) else _display(value, 1000)


def component_rows(payload: Any) -> List[Dict[str, Any]]:
    data = _mapping(payload)
    rows: List[Dict[str, Any]] = []
    for key, label in COMPONENT_LABELS.items():
        value = data.get(key)
        rows.append(
            {
                "key": key,
                "label": label,
                "value": _display(value),
                "missing": _missing(value),
            }
        )
    return rows


def component_cards_markdown(before: Any, after: Any) -> str:
    before_card = key_value_markdown(
        component_rows(before),
        title="Before",
        description="Live pipeline before the rebuild.",
    )
    after_card = key_value_markdown(
        component_rows(after),
        title="After",
        description="Candidate pipeline after the rebuild.",
    )
    return f'<div class="genai-diff-cards">{before_card}{after_card}</div>'


def diff_tone(before: Any, after: Any) -> str:
    if _missing(before) and not _missing(after):
        return "better"
    if not _missing(before) and _missing(after):
        return "worse"
    return "neutral"


def _change(before: Any, after: Any) -> str:
    if _normalized(before) == _normalized(after):
        return "unchanged"
    tone = diff_tone(before, after)
    return {"better": "added", "worse": "removed", "neutral": "changed"}[tone]


def _row_tone(before: Any, after: Any, change: str) -> str:
    if change in {"added", "removed"}:
        return diff_tone(before, after)
    return "neutral"


def component_delta_rows(before: Any, after: Any) -> List[Dict[str, Any]]:
    before_data = _mapping(before)
    after_data = _mapping(after)
    rows: List[Dict[str, Any]] = []
    for key, label in COMPONENT_LABELS.items():
        before_value = before_data.get(key)
        after_value = after_data.get(key)
        change = _change(before_value, after_value)
        rows.append(
            {
                "key": key,
                "field": label,
                "before": _display(before_value),
                "after": _display(after_value),
                "change": change,
                "tone": _row_tone(before_value, after_value, change),
            }
        )
    return rows


def delta_table_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-card genai-muted">No deltas available.</div>'
    parts = [
        '<div class="genai-table-scroll"><table class="genai-diff-table">',
        "<thead><tr><th>Field</th><th>Before</th><th>After</th><th>Change</th></tr></thead><tbody>",
    ]
    for row in rows:
        tone = _text(row.get("tone")).lower()
        if tone not in TONES:
            tone = "neutral"
        parts.append(
            "<tr>"
            f'<td>{escape(_text(row.get("field")) or "-")}</td>'
            f'<td>{escape(_text(row.get("before")) or "-")}</td>'
            f'<td>{escape(_text(row.get("after")) or "-")}</td>'
            f'<td><span class="genai-delta genai-delta-{tone}">'
            f'{escape(_text(row.get("change")) or "-")}</span></td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _find_key(node: Any, key: str, depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(node, Mapping):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, (list, tuple)):
        for value in node:
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    return None


def _config_value(config: Mapping[str, Any], key: str) -> Any:
    node: Any = config
    path = OVERRIDE_PATHS.get(key)
    if path:
        for part in path:
            node = _mapping(node).get(part)
            if node is None:
                return None
        return node
    return _find_key(config, key)


def override_delta_rows(
    before_config: Any,
    after_config: Any,
    applied_overrides: Any,
) -> List[Dict[str, Any]]:
    applied = _mapping(applied_overrides)
    before = _mapping(before_config)
    after = _mapping(after_config)
    rows: List[Dict[str, Any]] = []
    for key in sorted(applied):
        requested = applied.get(key)
        before_value = _config_value(before, key)
        after_value = _config_value(after, key)
        if _missing(after_value):
            after_value = requested
        change = _change(before_value, after_value)
        rows.append(
            {
                "key": key,
                "field": _text(key).replace("_", " ").title(),
                "before": _display(before_value),
                "after": _display(after_value),
                "change": change,
                "tone": _row_tone(before_value, after_value, change),
            }
        )
    return rows


def compare_view_models(
    before_ready: Any,
    rebuild: Any,
    before_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    before_payload = _mapping(before_ready)
    rebuild_payload = _mapping(rebuild)
    before_components = _mapping(before_payload.get("components"))
    after_components = _mapping(rebuild_payload.get("components"))
    applied = _mapping(rebuild_payload.get("applied_overrides"))
    before_available = bool(
        before_components or before_payload.get("config_revision") is not None
    )
    components = component_delta_rows(before_components, after_components)
    overrides = override_delta_rows(
        before_config or {},
        rebuild_payload.get("effective_config"),
        applied,
    )
    changed = sum(1 for row in components if row["change"] != "unchanged")
    revision = rebuild_payload.get("config_revision", "-")
    kpis = kpi_strip(
        [
            {"label": "Config revision", "value": revision},
            {
                "label": "Components changed",
                "value": changed,
                "status": "warning" if changed else "ok",
            },
            {
                "label": "Overrides applied",
                "value": len(applied),
                "status": "ok" if applied else "neutral",
            },
            {
                "label": "Before snapshot",
                "value": "available" if before_available else "unavailable",
                "status": "ok" if before_available else "warning",
            },
        ]
    )
    return {
        "kpis": kpis,
        "cards": component_cards_markdown(before_components, after_components),
        "components": components,
        "overrides": overrides,
        "before_available": before_available,
        "revision": revision,
        "raw": redact_payload({"before": dict(before_payload), "rebuild": dict(rebuild_payload)}),
    }
