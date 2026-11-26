"""Trust banners, action hierarchy, and progress cues for the console (#256).

Helpers in this module are intentionally pure: they build escaped view models and
markdown fragments only. Streamlit imports and backend imports stay in ``ui/app.py``.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any, Dict, Mapping, Optional

from ui.components import redact_payload

TRUST_BANNERS: Dict[str, Dict[str, str]] = {
    "demo": {
        "label": "Demo",
        "title": "Demo data",
        "tone": "warning",
        "message": "Local fixtures only; no backend requests are made.",
    },
    "redacted": {
        "label": "Redacted",
        "title": "Redacted view",
        "tone": "info",
        "message": "Sensitive values are masked in this view.",
    },
    "read_only": {
        "label": "Read-only",
        "title": "Read-only view",
        "tone": "info",
        "message": "Configuration is managed as YAML; this screen does not edit files.",
    },
    "tenant_scoped": {
        "label": "Scoped",
        "title": "Tenant-scoped",
        "tone": "warning",
        "message": "Results are limited to the resolved tenant scope.",
    },
    "admin_confirm": {
        "label": "Admin action",
        "title": "Administrative action",
        "tone": "warning",
        "message": "This changes shared configuration and is recorded in the audit trail.",
    },
    "destructive": {
        "label": "Destructive",
        "title": "Destructive action",
        "tone": "danger",
        "message": "This action cannot be undone; check the target before continuing.",
    },
}

ACTION_HIERARCHIES: Dict[str, str] = {
    "primary": "primary",
    "secondary": "secondary",
    "destructive": "secondary",
    "admin": "secondary",
}

PROGRESS_LABELS: Dict[str, str] = {
    "batch": "Running batch...",
    "eval_job": "Evaluating cases...",
    "query": "Running query...",
    "rebuild": "Rebuilding pipeline...",
    "approvals": "Loading approvals...",
}

__all__ = [
    "ACTION_HIERARCHIES",
    "PROGRESS_LABELS",
    "TRUST_BANNERS",
    "action_markdown",
    "action_model",
    "button_kwargs",
    "confirmation_copy",
    "progress_markdown",
    "progress_model",
    "trust_banner_markdown",
    "trust_banner_model",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _detail_text(detail: Any) -> str:
    if isinstance(detail, Mapping):
        safe = redact_payload(detail)
        try:
            return json.dumps(safe, default=str, sort_keys=True)
        except (TypeError, ValueError):
            return str(safe)
    return _text(detail)


def trust_banner_model(
    kind: str,
    detail: Any = None,
    scope: Any = None,
) -> Dict[str, Any]:
    """Build a normalized trust banner model for a known mode."""
    normalized = _text(kind).strip().lower()
    preset = TRUST_BANNERS.get(normalized, TRUST_BANNERS["redacted"])
    return {
        "kind": normalized if normalized in TRUST_BANNERS else "redacted",
        "label": preset["label"],
        "title": preset["title"],
        "tone": preset["tone"],
        "message": preset["message"],
        "detail": _detail_text(detail),
        "scope": _text(scope),
    }


def trust_banner_markdown(banner: Mapping[str, Any]) -> str:
    """Render a banner as escaped HTML with a semantic role."""
    tone = _text(banner.get("tone")) or "info"
    title = _text(banner.get("title")) or "Notice"
    message = _text(banner.get("message"))
    parts = [
        f'<div class="genai-trust-banner genai-trust-banner-{escape(tone)}" role="status">',
        f'<span class="genai-trust-label">{escape(_text(banner.get("label")) or "Notice")}</span>',
        f'<div class="genai-trust-title">{escape(title)}</div>',
    ]
    if message:
        parts.append(f'<div class="genai-trust-message">{escape(message)}</div>')
    if banner.get("scope"):
        parts.append(f'<div class="genai-trust-scope">{escape(_text(banner["scope"]))}</div>')
    if banner.get("detail"):
        parts.append(f'<div class="genai-trust-detail">{escape(_text(banner["detail"]))}</div>')
    parts.append("</div>")
    return "".join(parts)


def action_model(
    label: Any,
    hierarchy: str = "secondary",
    help: Any = None,
    detail: Any = None,
) -> Dict[str, Any]:
    """Normalize a button label and its primary/secondary/destructive/admin role."""
    normalized = _text(hierarchy).strip().lower()
    if normalized not in ACTION_HIERARCHIES:
        normalized = "secondary"
    return {
        "label": _text(label) or "Continue",
        "hierarchy": normalized,
        "type": ACTION_HIERARCHIES[normalized],
        "help": _text(help),
        "detail": _detail_text(detail),
    }


def button_kwargs(action: Mapping[str, Any]) -> Dict[str, Any]:
    """Return Streamlit-button keyword arguments for an action model."""
    kwargs: Dict[str, Any] = {"type": action.get("type") or "secondary"}
    if action.get("help"):
        kwargs["help"] = _text(action["help"])
    return kwargs


def confirmation_copy(action: Mapping[str, Any]) -> str:
    """Return the standard confirmation sentence for admin/destructive actions."""
    hierarchy = _text(action.get("hierarchy")).strip().lower()
    if hierarchy == "destructive":
        return "Confirm this destructive action. It cannot be undone."
    if hierarchy == "admin":
        return "Confirm this administrative action. It changes shared state and is audited."
    return ""


def action_markdown(action: Mapping[str, Any]) -> str:
    """Render an action hierarchy as a small escaped HTML chip."""
    hierarchy = _text(action.get("hierarchy")) or "secondary"
    label = _text(action.get("label")) or "Continue"
    return (
        f'<span class="genai-action genai-action-{escape(hierarchy)}">'
        f"{escape(label)}</span>"
    )


def progress_model(
    kind: str,
    done: Optional[float] = None,
    total: Optional[float] = None,
    status: str = "running",
    detail: Any = None,
) -> Dict[str, Any]:
    """Build a normalized loading/progress model for long-running operations."""
    normalized = _text(kind).strip().lower()
    label = PROGRESS_LABELS.get(normalized, "Working...")
    fraction: Optional[float] = None
    percent: Optional[int] = None
    if done is not None and total:
        try:
            fraction = min(1.0, max(0.0, float(done) / float(total)))
            percent = int(round(fraction * 100))
        except (TypeError, ValueError, ZeroDivisionError):
            fraction = None
            percent = None
    text = label
    if percent is not None:
        text = f"{label} {percent}%"
    normalized_status = _text(status).strip().lower() or "running"
    if normalized_status != "running":
        text = f"{normalized_status.title()}: {text}"
    return {
        "kind": normalized,
        "status": normalized_status,
        "label": label,
        "text": text,
        "fraction": fraction,
        "percent": percent,
        "detail": _detail_text(detail),
    }


def progress_markdown(progress: Mapping[str, Any]) -> str:
    """Render a loading note with a deterministic progress bar or skeleton."""
    status = _text(progress.get("status")) or "running"
    text = _text(progress.get("text")) or "Working..."
    parts = [
        f'<div class="genai-progress-note genai-progress-note-{escape(status)}" role="status">',
        f'<span class="genai-progress-text">{escape(text)}</span>',
    ]
    fraction = progress.get("fraction")
    if isinstance(fraction, (int, float)):
        percent = max(0, min(100, int(round(float(fraction) * 100))))
        parts.append(
            '<span class="genai-progress-track">'
            f'<span class="genai-progress-fill" style="width:{percent}%"></span>'
            "</span>"
        )
    else:
        parts.append('<span class="genai-progress-skeleton" aria-hidden="true"></span>')
    if progress.get("detail"):
        parts.append(f'<span class="genai-progress-detail">{escape(_text(progress["detail"]))}</span>')
    parts.append("</div>")
    return "".join(parts)
