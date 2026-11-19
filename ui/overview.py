"""Pure view-model helpers for the Overview / Health screen (issue #242).

No Streamlit or backend imports: all API payloads are normalized into escaped
HTML fragments and structured view models consumed by thin renderers.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ui.components import (
    badge_markdown,
    badge_model,
    detail_drawer_model,
    key_value_markdown,
    key_value_rows,
    redact_payload,
    section_card_markdown,
    section_card_model,
)
from ui.navigation import checklist_status
from ui.shell import health_view, scope_view

RAW_EXPANDER_LABEL = "Raw (redacted)"

_DISCOVERY_LABELS = {
    "models": "Active model",
    "retrievers": "Retriever",
    "rerankers": "Reranker",
    "evaluators": "Evaluator",
}

__all__ = [
    "RAW_EXPANDER_LABEL",
    "active_label",
    "checklist_card_view",
    "component_cards",
    "component_cards_markdown",
    "overview_kpis",
    "raw_detail_drawer",
]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _ok(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value.get("ok"))
    return bool(getattr(value, "ok", False))


def _data(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return _as_mapping(value.get("data"))
    return _as_mapping(getattr(value, "data", None))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _title(key: Any) -> str:
    return _text(key).replace("_", " ").title() or "Component"


def active_label(label: str, data: Any) -> str:
    """Resolve the active component name from a discovery payload."""
    payload = _as_mapping(data)
    if label == "Active model":
        return _text(payload.get("active") or "-") or "-"
    if label == "Retriever":
        return _text(payload.get("default_retriever") or "-") or "-"
    if label == "Reranker":
        return _text(
            payload.get("active_reranker")
            or ("disabled" if not payload.get("enabled", True) else "-")
        )
    return _text(
        payload.get("active_evaluator")
        or ("disabled" if not payload.get("enabled", True) else "-")
    )


def _status_for_value(value: str) -> str:
    if value == "disabled":
        return "disabled"
    if value in {"", "-"}:
        return "neutral"
    return "ok"


def overview_kpis(
    health: Any,
    ready: Any,
    access: Any = None,
    discovery: Optional[Mapping[str, Any]] = None,
    environment: str = "local",
) -> List[Dict[str, Any]]:
    """Build the Overview KPI strip from health, readiness and discovery results."""
    health_state = health_view(health, ready)
    ready_data = _data(ready)
    scope = scope_view(access, environment)
    kpis: List[Dict[str, Any]] = [
        {
            "label": "API health",
            "value": _data(health).get("status") or health_state["label"],
            "status": badge_model(
                "ok" if health_state["health_ok"] else "error",
                _text(_data(health).get("status") or health_state["label"]),
            ),
            "hint": health_state["detail"],
        },
        {
            "label": "Readiness",
            "value": ready_data.get("status") or health_state["label"],
            "status": badge_model(
                "ok" if health_state["ready_ok"] else "error",
                _text(ready_data.get("status") or health_state["label"]),
            ),
            "hint": "config revision: " + _text(ready_data.get("config_revision") or "-"),
        },
        {
            "label": "Config revision",
            "value": ready_data.get("config_revision") or "-",
            "status": badge_model("ok" if ready_data.get("config_revision") else "neutral"),
            "hint": "active pipeline",
        },
        {
            "label": "Tenant",
            "value": scope["scope"],
            "status": badge_model(scope["rbac"], scope["role"]),
            "hint": scope["environment"],
        },
    ]
    for key, label in _DISCOVERY_LABELS.items():
        result = (discovery or {}).get(key)
        if result is None or not _ok(result):
            value = "unavailable"
            status = "error"
        else:
            value = active_label(label, _data(result))
            status = _status_for_value(value)
        kpis.append(
            {
                "label": label,
                "value": value,
                "status": badge_model(status, value),
                "hint": "discovery: " + key,
            }
        )
    return kpis


def component_cards(components: Any) -> List[Dict[str, Any]]:
    """Turn the readiness component map into structured key-value cards."""
    source = _as_mapping(components)
    if not source:
        return []
    cards: List[Dict[str, Any]] = []
    for key, value in source.items():
        if isinstance(value, Mapping):
            rows = key_value_rows(value)
            payload = dict(value)
        else:
            rows = key_value_rows({"value": value})
            payload = {"value": value}
        card = section_card_model(
            _title(key),
            description=f"{len(rows)} field(s) reported by readiness",
            body_html=key_value_markdown(rows),
        )
        card["rows"] = rows
        card["payload"] = redact_payload(payload)
        cards.append(card)
    return cards


def component_cards_markdown(cards: Sequence[Mapping[str, Any]]) -> str:
    """Render component cards, falling back to an empty-state card."""
    if not cards:
        return '<div class="genai-card genai-muted">No registered components reported.</div>'
    return "".join(section_card_markdown(card) for card in cards)


def raw_detail_drawer(health: Any, ready: Any) -> Dict[str, Any]:
    """Build a redacted health/readiness detail drawer for an expander."""
    health_status = _text(_data(health).get("status") or "-")
    ready_status = _text(_data(ready).get("status") or "-")
    return detail_drawer_model(
        "Health and readiness detail",
        {
            "api_health": health_status or "-",
            "readiness": ready_status or "-",
            "config_revision": _text(_data(ready).get("config_revision") or "-"),
        },
        {
            "health": _data(health),
            "ready": _data(ready),
        },
        RAW_EXPANDER_LABEL,
    )


def checklist_card_view(
    done: Mapping[str, bool],
    capabilities: Optional[Iterable[str]] = None,
    statuses: Optional[Sequence[Tuple[Any, bool]]] = None,
) -> Dict[str, Any]:
    """Build the guided onboarding card from real session flags and capabilities."""
    resolved = checklist_status(done, capabilities) if statuses is None else [
        (step, bool(is_done)) for step, is_done in statuses
    ]
    completed = sum(1 for _, is_done in resolved if is_done)
    total = len(resolved)
    rows: List[Dict[str, Any]] = []
    for step, is_done in resolved:
        badge = badge_model("success" if is_done else "pending", "Done" if is_done else "To do")
        rows.append(
            {
                "key": step.key,
                "label": step.label,
                "detail": step.detail,
                "screen": step.screen or "sidebar",
                "done": is_done,
                "badge": badge,
                "badge_html": badge_markdown(badge),
            }
        )
    pending = [row for row in rows if not row["done"] and row["screen"] != "sidebar"]
    nxt = pending[0] if pending else None
    list_items = "".join(
        '<li class="genai-checklist-item">'
        f'{row["badge_html"]} '
        f'<strong>{escape(row["label"])}</strong>'
        f'<span class="genai-muted"> - {escape(row["detail"])}</span>'
        f'<span class="genai-muted"> ({escape(row["screen"])})</span>'
        "</li>"
        for row in rows
    )
    progress = completed / total if total else 0.0
    card = section_card_model(
        "Get started",
        description=f"{completed} of {total} steps complete for your role",
        body_html=f'<ol class="genai-checklist">{list_items}</ol>',
        actions=[f"Next: {nxt['label']}" if nxt else "All available steps complete"],
    )
    return {
        "rows": rows,
        "card": card,
        "completed": completed,
        "total": total,
        "progress": progress,
        "complete": total > 0 and completed == total,
        "next": nxt,
        "card_markdown": section_card_markdown(card),
    }
