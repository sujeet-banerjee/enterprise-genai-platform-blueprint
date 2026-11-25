"""Structured read-only Settings presentation for the console (#253).

Pure module: no Streamlit or backend imports. It consumes already-fetched API
payloads and returns escaped view models for ``ui/app.py``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ui.components import (
    format_bool,
    key_value_markdown,
    key_value_rows,
    kpi_model,
    kpi_strip,
    kpi_strip_markdown,
    redact_payload,
    section_card_markdown,
    section_card_model,
)

RAW_EXPANDER_LABEL = "Raw (redacted)"

SECRET_VALUE_RE = re.compile(
    r"\bsk-[A-Za-z0-9_-]{8,}\b|\bBearer\s+[^\s]+",
    re.IGNORECASE,
)
ENV_REFERENCE_RE = re.compile(r"\$\{[^}]+\}|\benv:[A-Za-z_][A-Za-z0-9_]*", re.IGNORECASE)

SECTION_SPECS: Tuple[Tuple[str, str, Tuple[str, ...], Optional[str], Optional[str]], ...] = (
    ("Models", "Active model, embedding model and provider definitions.", ("models",), "models", "models"),
    (
        "Retrieval",
        "Default retriever, similarity metric and retrieval providers.",
        ("retrieval.retrieval", "retrieval"),
        "retrievers",
        "retrievers",
    ),
    (
        "Reranking",
        "Reranking policy and active reranker.",
        ("retrieval.reranking", "reranking"),
        "rerankers",
        "rerankers",
    ),
    (
        "Evaluation",
        "Evaluator policy, active evaluator and available evaluators.",
        ("retrieval.evaluation", "evaluation"),
        "evaluators",
        "evaluators",
    ),
    ("Guardrails", "Safety profile and configured guardrail chains.", ("guardrails",), "guardrails", "guardrails"),
    ("Observability", "Logging, tracing, redaction, PII and audit settings.", ("observability",), None, None),
    ("Cache", "Response cache size and expiry policy.", ("retrieval.cache", "cache"), None, None),
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).strip()


def _scrub_string(value: str) -> str:
    scrubbed = SECRET_VALUE_RE.sub("[REDACTED]", value)
    return ENV_REFERENCE_RE.sub("[ENV REFERENCE]", scrubbed)


def redact_settings_payload(value: Any) -> Any:
    """Mask secret-like keys, literal credentials and environment references."""
    safe = redact_payload(value)
    if isinstance(safe, Mapping):
        return {str(key): redact_settings_payload(item) for key, item in safe.items()}
    if isinstance(safe, (list, tuple, set)):
        return [redact_settings_payload(item) for item in safe]
    if isinstance(safe, str):
        return _scrub_string(safe)
    return safe


def _nested(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _first_payload(data: Mapping[str, Any], paths: Iterable[str]) -> Mapping[str, Any]:
    for path in paths:
        value = _mapping(_nested(data, path))
        if value:
            return value
    return {}


def _first_scalar(data: Mapping[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        value = _nested(data, path)
        if value is not None and value != "":
            return value
    return None


def _field(data: Mapping[str, Any], name: str) -> Any:
    value = data.get(name)
    return value if value is not None and value != "" else None


def _entries(value: Any) -> List[Any]:
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _provider_values(value: Any) -> List[str]:
    names: List[str] = []
    for entry in _entries(value):
        if isinstance(entry, Mapping):
            for key in ("provider", "name", "key"):
                candidate = _text(entry.get(key))
                if candidate:
                    names.append(candidate)
                    break
        elif isinstance(entry, str) and entry.strip():
            names.append(entry.strip())
    return names


def _provider_count(value: Any) -> int:
    if isinstance(value, Mapping):
        return len(value)
    return len(_entries(value))


def _display_path(path: str) -> str:
    return path.replace(".", " › ").replace("_", " ")


def flatten_config_rows(data: Any, max_rows: int = 12) -> List[Dict[str, Any]]:
    """Flatten a config mapping into bounded, redacted key-value rows."""
    safe = redact_settings_payload(data)
    if not isinstance(safe, Mapping):
        return key_value_rows({"value": safe}, {"value": "Value"})
    values: Dict[str, Any] = {}
    labels: Dict[str, str] = {}
    truncated = False

    def walk(value: Any, path: str) -> None:
        nonlocal truncated
        if len(values) >= max_rows:
            truncated = True
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{path}.{str(key)}" if path else str(key))
            return
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            scalar_items = all(not isinstance(item, (Mapping, list, tuple, set)) for item in items)
            if scalar_items and items:
                values[path] = ", ".join(_text(item) for item in items)
            else:
                values[path] = f"{len(items)} items"
        else:
            values[path] = value
        labels[path] = _display_path(path)

    for key, item in safe.items():
        walk(item, str(key))
    if truncated:
        values["raw_view"] = "Full configuration is in Raw (redacted) below."
        labels["raw_view"] = "Full detail"
    return key_value_rows(values, labels)


def provider_rows(kind: str, payload: Any) -> List[Dict[str, Any]]:
    """Summarize an introspection payload as redacted key-value rows."""
    data = _mapping(redact_settings_payload(payload))
    if not data:
        return []
    if kind == "models":
        summary = {
            "active": _field(data, "active") or _field(data, "active_model") or "-",
            "definitions": _provider_count(data.get("models")),
            "providers": ", ".join(_provider_values(data.get("models"))) or "-",
        }
    elif kind == "embedding-models":
        summary = {
            "active": _field(data, "active") or _field(data, "active_embedding_model") or "-",
            "definitions": _provider_count(data.get("embedding_models")),
            "providers": ", ".join(_provider_values(data.get("embedding_models"))) or "-",
        }
    elif kind == "retrievers":
        summary = {
            "default": _field(data, "default_retriever") or "-",
            "similarity_metric": _field(data, "similarity_metric") or "-",
            "providers": ", ".join(_provider_values(data.get("providers"))) or "-",
        }
    elif kind == "rerankers":
        summary = {
            "enabled": format_bool(_field(data, "enabled")),
            "active": _field(data, "active_reranker") or "-",
            "providers": ", ".join(_provider_values(data.get("providers"))) or "-",
        }
    elif kind == "evaluators":
        summary = {
            "enabled": format_bool(_field(data, "enabled")),
            "active": _field(data, "active_evaluator") or "-",
            "providers": ", ".join(_provider_values(data.get("providers"))) or "-",
        }
    elif kind == "guardrails":
        summary = {
            "enabled": format_bool(_field(data, "enabled")),
            "profile": _field(data, "profile") or "none",
            "input_rules": _provider_count(data.get("input")),
            "output_rules": _provider_count(data.get("output")),
            "errors": _provider_count(data.get("errors")),
        }
    else:
        return []
    return key_value_rows(summary)


def config_sections(
    config: Any,
    providers: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build grouped Settings cards from effective config and provider payloads."""
    safe_config = _mapping(redact_settings_payload(config))
    safe_providers = _mapping(redact_settings_payload(providers or {}))
    sections: List[Dict[str, Any]] = []
    for title, description, paths, provider_key, provider_kind in SECTION_SPECS:
        rows = flatten_config_rows(_first_payload(safe_config, paths))
        body = key_value_markdown(rows, title="Effective values", description=description)
        if provider_key and provider_kind:
            extra = provider_rows(provider_kind, _first_payload(safe_providers, (provider_key,)))
            if extra:
                body += key_value_markdown(extra, title="Runtime providers", description="Live introspection")
        sections.append(
            {
                "key": title.lower().replace(" ", "_"),
                "title": title,
                "description": description,
                "rows": rows,
                "provider_rows": provider_rows(
                    provider_kind or "",
                    _first_payload(safe_providers, (provider_key,) if provider_key else ()),
                ),
                "body_html": body,
            }
        )
    return sections


def settings_kpis(
    config: Any,
    providers: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build the Settings summary strip from effective config and introspection."""
    safe_config = _mapping(redact_settings_payload(config))
    safe_providers = _mapping(redact_settings_payload(providers or {}))
    models = _first_payload(safe_providers, ("models",))
    retrievers = _first_payload(safe_providers, ("retrievers",))
    rerankers = _first_payload(safe_providers, ("rerankers",))
    evaluators = _first_payload(safe_providers, ("evaluators",))
    active_model = _first_scalar(safe_config, ("models.active_model",)) or _field(models, "active")
    active_retriever = _first_scalar(
        safe_config, ("retrieval.retrieval.default_retriever", "retrieval.default_retriever")
    ) or _field(retrievers, "default_retriever")
    rerank_raw = _first_scalar(safe_config, ("retrieval.reranking.enabled", "reranking.enabled"))
    if rerank_raw is None:
        rerank_raw = _field(rerankers, "enabled")
    cache_raw = _first_scalar(safe_config, ("retrieval.cache.enabled", "cache.enabled"))
    active_evaluator = _first_scalar(
        safe_config, ("retrieval.evaluation.active_evaluator", "evaluation.active_evaluator")
    ) or _field(evaluators, "active_evaluator")
    return kpi_strip(
        [
            kpi_model("Active model", _text(active_model) or "-", hint="models.yaml"),
            kpi_model("Retriever", _text(active_retriever) or "-", hint="retrieval.yaml"),
            kpi_model("Reranking", format_bool(rerank_raw, "Enabled", "Disabled"), hint="reranking.enabled"),
            kpi_model("Evaluator", _text(active_evaluator) or "-", hint="evaluation.active_evaluator"),
            kpi_model("Cache", format_bool(cache_raw, "Enabled", "Disabled"), hint="cache.enabled"),
        ]
    )


def settings_sections_markdown(sections: Sequence[Mapping[str, Any]]) -> str:
    """Render grouped Settings cards as escaped, responsive HTML."""
    cards = [
        section_card_markdown(
            section_card_model(
                section.get("title"),
                section.get("description"),
                section.get("body_html"),
            )
        )
        for section in sections
    ]
    if not cards:
        return '<div class="genai-card genai-muted">No configuration sections available.</div>'
    return f'<div class="genai-settings-sections">{"".join(cards)}</div>'


def settings_view_models(
    config: Any = None,
    providers: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the complete read-only Settings view model."""
    safe_config = _mapping(redact_settings_payload(config))
    safe_providers = _mapping(redact_settings_payload(providers or {}))
    sections = config_sections(safe_config, safe_providers)
    kpis = settings_kpis(safe_config, safe_providers)
    return {
        "kpis": kpis,
        "kpis_markdown": kpi_strip_markdown(kpis),
        "sections": sections,
        "sections_markdown": settings_sections_markdown(sections),
        "raw": {"config": safe_config, "providers": safe_providers},
        "expander_label": RAW_EXPANDER_LABEL,
    }
