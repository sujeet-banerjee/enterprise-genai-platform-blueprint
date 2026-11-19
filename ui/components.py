"""Pure design-system primitives for the Streamlit console (issue #241).

No Streamlit or backend imports. Helpers return view models and escaped HTML
fragments consumed by thin renderers in ``ui/app.py`` and ``ui/common.py``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ui.polish import error_remediation
from ui.theme import STATUS_TONES, status_color

SECRET_KEY_HINTS = ("api_key", "token", "secret", "password", "authorization", "credential")
BADGE_TONES = ("success", "warning", "danger", "neutral")
DETAIL_EXPANDER_LABEL = "Raw payload (redacted)"

__all__ = [
    "BADGE_TONES",
    "DETAIL_EXPANDER_LABEL",
    "SECRET_KEY_HINTS",
    "alert_markdown",
    "alert_model",
    "badge_markdown",
    "badge_model",
    "detail_drawer_markdown",
    "detail_drawer_model",
    "empty_alert_model",
    "error_alert_model",
    "failure_alert_model",
    "format_bool",
    "format_count",
    "format_cost_usd",
    "format_duration_ms",
    "format_timestamp",
    "key_value_markdown",
    "key_value_rows",
    "kpi_strip",
    "kpi_strip_markdown",
    "redact_payload",
    "section_card_markdown",
    "section_card_model",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _truncate(value: str, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_secret_key(key: Any) -> bool:
    lowered = _text(key).lower()
    return any(hint in lowered for hint in SECRET_KEY_HINTS)


def _badge_tone(status: Any) -> str:
    key = _text(status).lower()
    tone = STATUS_TONES.get(key)
    if tone in {"success", "warning", "danger"}:
        return str(tone)
    return "neutral"


def format_timestamp(value: Any, fallback: str = "-") -> str:
    """Normalize datetime, epoch and ISO-8601 values without raising."""
    if value is None or isinstance(value, bool):
        return fallback
    moment: Optional[datetime]
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        try:
            seconds = float(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        if not math.isfinite(seconds):
            return fallback
        if seconds > 100_000_000_000:
            seconds /= 1000.0
        try:
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return fallback
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return fallback
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return _truncate(text, 80)
    else:
        return _truncate(_text(value), 80) or fallback
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_duration_ms(value: Any, fallback: str = "-") -> str:
    """Render millisecond durations compactly, safely handling odd values."""
    if value is None or isinstance(value, bool):
        return fallback
    try:
        milliseconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(milliseconds) or milliseconds < 0:
        return fallback
    if milliseconds < 1:
        return f"{milliseconds:.2f} ms"
    if milliseconds < 1000:
        return f"{milliseconds:.1f} ms"
    if milliseconds < 60_000:
        return f"{milliseconds / 1000:.2f} s"
    return f"{milliseconds / 60_000:.1f} min"


def format_cost_usd(value: Any, fallback: str = "-") -> str:
    """Format USD costs with enough precision for small per-request values."""
    if value is None or isinstance(value, bool):
        return fallback
    raw = _text(value).replace("$", "").replace(",", "")
    if not raw:
        return fallback
    try:
        amount = float(raw)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(amount):
        return fallback
    if abs(amount) < 1:
        return f"${amount:,.4f}"
    return f"${amount:,.2f}"


def format_count(value: Any, fallback: str = "0") -> str:
    """Render counts with thousands separators; never raise on odd input."""
    if value is None or isinstance(value, bool) or value == "":
        return fallback
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return _truncate(_text(value), 80) or fallback
    return f"{number:,}"


def format_bool(value: Any, yes: str = "Yes", no: str = "No", fallback: str = "-") -> str:
    """Map booleans and common string forms to a stable yes/no label."""
    if isinstance(value, bool):
        return yes if value else no
    if value is None:
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return yes
        if value == 0:
            return no
        return fallback
    lowered = _text(value).lower()
    if lowered in {"true", "yes", "y", "1", "on"}:
        return yes
    if lowered in {"false", "no", "n", "0", "off"}:
        return no
    return fallback


def format_auto(value: Any) -> str:
    """Best-effort display formatter for mixed API payload values."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return format_bool(value)
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, (int, float)):
        return format_count(value)
    return _truncate(_text(value), 160) or "-"


def redact_payload(value: Any) -> Any:
    """Recursively mask secret-looking keys in a JSON-like payload."""
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            result[name] = "[REDACTED]" if _is_secret_key(name) else redact_payload(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact_payload(item) for item in value]
    if isinstance(value, datetime):
        return format_timestamp(value)
    return value


def _json_text(value: Any) -> str:
    safe = redact_payload(value)
    try:
        rendered = json.dumps(safe, default=str, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(safe)
    return _truncate(rendered)


def _display_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return format_bool(value)
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return "-"
        if not math.isfinite(number):
            return "-"
        if number.is_integer():
            return format_count(number)
        return f"{number:,.6f}".rstrip("0").rstrip(".")
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return _json_text(value)
    return _truncate(_text(value), 160) or "-"


def badge_model(status: Any, label: Any = None) -> Dict[str, Any]:
    """Build a semantic badge view model from an API status word."""
    raw = _text(status)
    key = raw.lower() or "unknown"
    return {
        "label": _text(label) or raw or "unknown",
        "status": key,
        "tone": _badge_tone(key),
        "color": status_color(raw or None),
    }


def badge_markdown(badge: Mapping[str, Any]) -> str:
    tone = _text(badge.get("tone")).lower()
    if tone not in BADGE_TONES:
        tone = "neutral"
    label = escape(_text(badge.get("label")) or "unknown")
    return f'<span class="genai-chip genai-chip-{tone}">{label}</span>'


def kpi_model(
    label: Any,
    value: Any,
    delta: Any = None,
    hint: Any = None,
    status: Any = None,
) -> Dict[str, Any]:
    """Build one standardized KPI tile."""
    badge: Optional[Dict[str, Any]]
    if isinstance(status, Mapping):
        badge = dict(status)
    elif status is None or status == "":
        badge = None
    else:
        badge = badge_model(status)
    return {
        "label": _text(label) or "Metric",
        "value": _display_value(value),
        "delta": _text(delta),
        "hint": _text(hint),
        "status": badge,
    }


def kpi_strip(items: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    """Build a KPI strip view model, skipping unusable entries."""
    rows: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            kpi_model(
                item.get("label"),
                item.get("value", "-"),
                item.get("delta"),
                item.get("hint"),
                item.get("status"),
            )
        )
    return rows


def kpi_strip_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return '<div class="genai-kpi-strip genai-muted">No metrics available.</div>'
    tiles: List[str] = []
    for row in rows:
        status = row.get("status")
        status_html = badge_markdown(status) if isinstance(status, Mapping) else ""
        delta = _text(row.get("delta"))
        hint = _text(row.get("hint"))
        meta_parts: List[str] = []
        if status_html:
            meta_parts.append(status_html)
        if delta:
            meta_parts.append(f'<span class="genai-kpi-delta">{escape(delta)}</span>')
        if hint:
            meta_parts.append(f'<span class="genai-muted">{escape(hint)}</span>')
        meta = f'<div class="genai-kpi-meta">{"".join(meta_parts)}</div>' if meta_parts else ""
        tiles.append(
            '<div class="genai-kpi">'
            f'<div class="genai-kpi-label">{escape(_text(row.get("label")) or "Metric")}</div>'
            f'<div class="genai-kpi-value">{escape(_text(row.get("value")) or "-")}</div>'
            f"{meta}</div>"
        )
    return f'<div class="genai-kpi-strip">{"".join(tiles)}</div>'


def key_value_rows(
    data: Any,
    labels: Optional[Mapping[Any, Any]] = None,
    redact: bool = True,
) -> List[Dict[str, Any]]:
    """Turn a mapping into labeled, redacted rows instead of a raw dict dump."""
    if data is None:
        return []
    if not isinstance(data, Mapping):
        return [{"label": "value", "value": _display_value(data), "sensitive": False}]
    names = labels or {}
    rows: List[Dict[str, Any]] = []
    for key, value in data.items():
        label = _text(names.get(key)) if key in names else _text(key).replace("_", " ").title()
        sensitive = redact and _is_secret_key(key)
        rows.append(
            {
                "label": label or "value",
                "value": "[REDACTED]" if sensitive else _display_value(value),
                "sensitive": sensitive,
            }
        )
    return rows


def key_value_markdown(
    rows: Sequence[Mapping[str, Any]],
    title: Any = None,
    description: Any = None,
) -> str:
    if not rows:
        return '<div class="genai-card genai-muted">No details available.</div>'
    fields = "".join(
        f"<dt>{escape(_text(row.get('label')) or 'value')}</dt>"
        f"<dd>{escape(_text(row.get('value')) or '-')}</dd>"
        for row in rows
    )
    heading = f"<h4>{escape(_text(title))}</h4>" if _text(title) else ""
    detail = (
        f'<p class="genai-card-description">{escape(_text(description))}</p>'
        if _text(description)
        else ""
    )
    return f'<div class="genai-card">{heading}{detail}<dl>{fields}</dl></div>'


def section_card_model(
    title: Any,
    description: Any = "",
    body_html: Any = "",
    actions: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    return {
        "title": _text(title) or "Details",
        "description": _text(description),
        "body_html": str(body_html or ""),
        "actions": [_text(action) for action in (actions or []) if _text(action)],
    }


def section_card_markdown(card: Mapping[str, Any]) -> str:
    title = escape(_text(card.get("title")) or "Details")
    description = _text(card.get("description"))
    desc_html = (
        f'<p class="genai-card-description">{escape(description)}</p>' if description else ""
    )
    actions = [escape(_text(action)) for action in card.get("actions") or [] if _text(action)]
    actions_html = (
        f'<div class="genai-actions">{"".join(actions)}</div>' if actions else ""
    )
    return (
        f'<section class="genai-card genai-section-card"><h4>{title}</h4>{desc_html}'
        f'{card.get("body_html") or ""}{actions_html}</section>'
    )


def detail_drawer_model(
    title: Any,
    summary: Any,
    payload: Any = None,
    expander_label: Any = DETAIL_EXPANDER_LABEL,
) -> Dict[str, Any]:
    return {
        "title": _text(title) or "Details",
        "summary_rows": key_value_rows(summary),
        "payload": redact_payload(payload if payload is not None else {}),
        "expander_label": _text(expander_label) or DETAIL_EXPANDER_LABEL,
    }


def detail_drawer_markdown(drawer: Mapping[str, Any]) -> str:
    label = _text(drawer.get("expander_label")) or DETAIL_EXPANDER_LABEL
    body = key_value_markdown(drawer.get("summary_rows") or [])
    body += f'<p class="genai-muted">{escape(label)} below.</p>'
    return section_card_markdown(
        section_card_model(
            drawer.get("title") or "Details",
            description="Curated summary",
            body_html=body,
        )
    )


def alert_model(
    title: Any,
    message: Any = "",
    failure_type: Any = None,
    tags: Any = None,
    request_id: Any = None,
    hint: Any = None,
    action: Any = None,
    tone: Any = "danger",
) -> Dict[str, Any]:
    if isinstance(tags, str):
        tag_list = [tags]
    else:
        tag_list = list(tags or [])
    normalized_tone = _text(tone).lower()
    if normalized_tone not in {"danger", "warning", "success", "info"}:
        normalized_tone = "danger"
    return {
        "title": _text(title) or "Request issue",
        "message": _text(message),
        "failure_type": _text(failure_type),
        "tags": [_text(tag) for tag in tag_list if _text(tag)],
        "request_id": _text(request_id),
        "hint": _text(hint),
        "action": _text(action),
        "tone": normalized_tone,
    }


def alert_markdown(alert: Mapping[str, Any]) -> str:
    tone = _text(alert.get("tone")).lower()
    if tone not in {"danger", "warning", "success", "info"}:
        tone = "danger"
    parts = [f'<div class="genai-alert genai-alert-{tone}" role="alert">']
    parts.append(f'<div class="genai-alert-title">{escape(_text(alert.get("title")) or "Issue")}</div>')
    message = _text(alert.get("message"))
    if message:
        parts.append(f'<div class="genai-alert-message">{escape(message)}</div>')
    meta: List[str] = []
    failure_type = _text(alert.get("failure_type"))
    if failure_type:
        meta.append(
            '<span class="genai-alert-code">'
            f"{escape(failure_type)}</span>"
        )
    for tag in alert.get("tags") or []:
        if _text(tag):
            meta.append(badge_model("neutral", tag))
    meta_html = "".join(
        item if isinstance(item, str) and item.startswith("<span") else escape(_text(item))
        for item in meta
    )
    if meta_html:
        parts.append(f'<div class="genai-alert-meta">{meta_html}</div>')
    request_id = _text(alert.get("request_id"))
    if request_id:
        parts.append(
            f'<div class="genai-alert-request">request_id: <code>{escape(request_id)}</code></div>'
        )
    hint = _text(alert.get("hint"))
    if hint:
        parts.append(f'<div class="genai-alert-hint">{escape(hint)}</div>')
    action = _text(alert.get("action"))
    if action:
        parts.append(f'<div class="genai-alert-action">{escape(action)}</div>')
    parts.append("</div>")
    return "".join(parts)


def empty_alert_model(message: Any, action: Any = "") -> Dict[str, Any]:
    return alert_model(
        title="No results",
        message=message,
        hint="Try widening the filters or changing the request.",
        action=action or "Adjust inputs and try again.",
        tone="info",
    )


def failure_alert_model(
    status_code: Any,
    failure_type: Any = "",
    tags: Any = None,
    request_id: Any = None,
    message: Any = "",
) -> Dict[str, Any]:
    try:
        status = int(status_code or 0)
    except (TypeError, ValueError, OverflowError):
        status = 0
    remediation = error_remediation(status, _text(failure_type))
    tone = "warning" if 400 <= status < 500 else "danger"
    return alert_model(
        title=remediation["title"],
        message=message or remediation["hint"],
        failure_type=failure_type,
        tags=tags,
        request_id=request_id,
        hint=remediation["hint"],
        action=remediation["action"],
        tone=tone,
    )


def error_alert_model(result: Any = None) -> Dict[str, Any]:
    """Build a structured alert from an ``ApiResult``-like object."""
    raw_status = getattr(result, "status_code", 0) or 0
    try:
        status = int(raw_status)
    except (TypeError, ValueError, OverflowError):
        status = 0
    failure_type = _text(getattr(result, "failure_type", "") or "")
    remediation = error_remediation(status, failure_type)
    data = getattr(result, "data", None)
    detail = ""
    if isinstance(data, Mapping):
        detail = _text(data.get("error") or data.get("detail") or data.get("message"))
    elif data is not None:
        detail = _truncate(_text(data), 160)
    detail = detail or _text(getattr(result, "error", "")) or "Request failed"
    tone = "warning" if 400 <= status < 500 else "danger"
    return alert_model(
        title=remediation["title"],
        message=detail,
        failure_type=failure_type or "unknown_failure",
        tags=getattr(result, "failure_tags", []) or [],
        request_id=getattr(result, "request_id", "") or "",
        hint=remediation["hint"],
        action=remediation["action"],
        tone=tone,
    )
