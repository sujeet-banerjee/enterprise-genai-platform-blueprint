"""Pure view models for the Guardrails console screen (issue #246).

No Streamlit or backend imports. Helpers consume ``/v1/guardrails`` and
per-request trace payloads and return escaped HTML or plain view models.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ui.components import (
    badge_markdown,
    badge_model,
    format_bool,
    key_value_markdown,
    key_value_rows,
    kpi_strip,
    redact_payload,
)
from ui.governance import guardrail_chart_data, guardrail_chart_markdown
from ui.theme import status_color

EDGE_LABELS = {"input": "Input", "output": "Output"}
EDGE_ORDER = ("input", "output")
DECISION_ORDER = ("allow", "redact", "block")

__all__ = [
    "DECISION_ORDER",
    "EDGE_LABELS",
    "EDGE_ORDER",
    "chain_cards",
    "chain_cards_markdown",
    "decision_badge",
    "decision_history_markdown",
    "decision_rows",
    "guardrail_view_models",
    "hit_rate_markdown",
    "hit_rate_rows",
    "hit_rate_summary",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _short(value: Any, limit: int = 180) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _labels(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [_text(item) for item in value if _text(item)]


def chain_cards(introspection: Mapping[str, Any]) -> List[Dict[str, Any]]:
    payload = _mapping(introspection)
    cards: List[Dict[str, Any]] = []
    for edge in EDGE_ORDER:
        entries = payload.get(edge) or []
        nodes: List[Dict[str, Any]] = []
        if isinstance(entries, (list, tuple)):
            for index, raw_entry in enumerate(entries):
                entry = _mapping(raw_entry)
                if not entry:
                    continue
                nodes.append(
                    {
                        "edge": edge,
                        "order": index + 1,
                        "provider": _text(entry.get("provider")) or "unknown",
                        "type": _text(entry.get("type")) or "-",
                        "stage": _text(entry.get("stage")) or edge,
                        "options": key_value_rows(entry.get("options")),
                    }
                )
        cards.append(
            {
                "edge": edge,
                "label": EDGE_LABELS[edge],
                "nodes": nodes,
                "count": len(nodes),
            }
        )
    return cards


def chain_cards_markdown(cards: Sequence[Mapping[str, Any]]) -> str:
    if not cards:
        return '<div class="genai-muted">No resolved chains available.</div>'
    parts = ['<div class="genai-guardrail-chain">']
    for card in cards:
        label = _text(card.get("label")) or _text(card.get("edge")) or "Chain"
        count = int(_number(card.get("count")) or 0)
        parts.append('<section class="genai-guardrail-edge">')
        parts.append(
            f"<h4>{escape(label)} chain "
            f'<span class="genai-guardrail-count">{count} step(s)</span></h4>'
        )
        nodes = card.get("nodes") or []
        if not nodes:
            parts.append('<div class="genai-muted">No guardrails configured on this edge.</div>')
        for index, raw_node in enumerate(nodes):
            node = _mapping(raw_node)
            if index:
                parts.append('<span class="genai-guardrail-arrow" aria-hidden="true">→</span>')
            provider = escape(_text(node.get("provider")) or "unknown")
            kind = escape(_text(node.get("type")) or "-")
            stage = escape(_text(node.get("stage")) or "-")
            order = int(_number(node.get("order")) or index + 1)
            options = node.get("options") or []
            options_html = (
                key_value_markdown(options, title="Options") if options else ""
            )
            parts.append(
                '<div class="genai-guardrail-node">'
                f'<span class="genai-guardrail-order">{order}</span>'
                '<div class="genai-guardrail-node-body">'
                f"<strong>{provider}</strong>"
                f'<div class="genai-muted">{kind} · {stage}</div>'
                f"{options_html}</div></div>"
            )
        parts.append("</section>")
    parts.append("</div>")
    return "".join(parts)


def decision_badge(decision: Any) -> Dict[str, Any]:
    key = _text(decision).lower() or "unknown"
    label = _text(decision) or "unknown"
    badge = badge_model(key, label)
    badge["tone"] = {
        "allow": "success",
        "redact": "warning",
        "block": "danger",
    }.get(key, "neutral")
    badge["color"] = status_color(key)
    return badge


def decision_rows(decisions: Sequence[Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, raw_record in enumerate(decisions or []):
        record = _mapping(raw_record)
        if not record:
            continue
        decision = _text(record.get("decision")) or "unknown"
        rows.append(
            {
                "index": index + 1,
                "guardrail": _text(record.get("guardrail")) or "unknown",
                "stage": _text(record.get("stage")) or "-",
                "decision": decision,
                "badge": decision_badge(decision),
                "allowed": format_bool(record.get("allowed"), fallback="-"),
                "reason": _short(record.get("reason")) or "-",
                "labels": ", ".join(_labels(record.get("labels"))) or "-",
                "raw": redact_payload(dict(record)),
            }
        )
    return rows


def decision_history_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-muted">No decision history recorded yet.</div>'
    parts = [
        '<div class="genai-table-scroll"><table class="genai-decision-table">',
        "<thead><tr><th>Guardrail</th><th>Stage</th><th>Outcome</th>"
        "<th>Allowed</th><th>Reason</th><th>Labels</th><th>Record</th></tr></thead><tbody>",
    ]
    for row in rows:
        badge = row.get("badge")
        badge_html = badge_markdown(badge) if isinstance(badge, Mapping) else ""
        raw_json = escape(json.dumps(row.get("raw") or {}, sort_keys=True, default=str))
        parts.append(
            "<tr>"
            f'<td>{escape(_text(row.get("guardrail")) or "unknown")}</td>'
            f'<td>{escape(_text(row.get("stage")) or "-")}</td>'
            f"<td>{badge_html}</td>"
            f'<td>{escape(_text(row.get("allowed")) or "-")}</td>'
            f'<td>{escape(_text(row.get("reason")) or "-")}</td>'
            f'<td>{escape(_text(row.get("labels")) or "-")}</td>'
            '<td><details class="genai-raw-record"><summary>Raw</summary>'
            f"<pre>{raw_json}</pre></details></td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def hit_rate_rows(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return guardrail_chart_data(metrics)


def hit_rate_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    return guardrail_chart_markdown(list(rows))


def hit_rate_summary(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    guardrails = _mapping(_mapping(metrics).get("guardrails"))
    by_decision = _mapping(guardrails.get("by_decision"))
    counts = {
        decision: max(int(_number(by_decision.get(decision)) or 0), 0)
        for decision in DECISION_ORDER
    }
    total = max(int(_number(guardrails.get("total_decisions")) or 0), 0)
    if not total:
        total = sum(counts.values())
    blocks = max(int(_number(guardrails.get("total_blocks")) or 0), 0)
    if not blocks:
        blocks = counts["block"]
    return {
        "total": total,
        "blocks": blocks,
        "redactions": counts["redact"],
        "allow_rate": round((counts["allow"] / total) * 100, 1) if total else 0.0,
    }


def guardrail_view_models(
    introspection: Mapping[str, Any],
    metrics: Optional[Mapping[str, Any]] = None,
    decisions: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    payload = _mapping(introspection)
    errors = [_text(item) for item in (payload.get("errors") or []) if _text(item)]
    enabled = bool(payload.get("enabled"))
    kpis = kpi_strip(
        [
            {
                "label": "Enabled",
                "value": "yes" if enabled else "no",
                "status": "ok" if enabled else "disabled",
            },
            {"label": "Profile", "value": _text(payload.get("profile")) or "none"},
            {"label": "Providers", "value": len(payload.get("providers") or [])},
            {
                "label": "Config errors",
                "value": len(errors),
                "status": "warning" if errors else "ok",
            },
        ]
    )
    return {
        "kpis": kpis,
        "chain": chain_cards(payload),
        "hit_rate": hit_rate_summary(metrics or {}),
        "hit_rate_rows": hit_rate_rows(metrics or {}),
        "decisions": decision_rows(decisions or []),
        "errors": errors,
    }
