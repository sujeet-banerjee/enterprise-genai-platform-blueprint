"""UX polish helpers (issue #136): a11y/tooltips, empty states, error remediation."""

from __future__ import annotations

from typing import Dict

TOOLTIPS = {
    "api_base": "Base URL of the FastAPI service (e.g., http://localhost:8000)",
    "api_key": "Optional API key if the service requires authentication",
    "top_k": "Number of documents to retrieve before reranking",
    "request_id": "Correlation id for traces and run history",
}


def tooltip(key: str, fallback: str = "") -> str:
    return TOOLTIPS.get(key, fallback)


def empty_state(message: str, action: str = "") -> Dict[str, str]:
    return {"message": message, "action": action or "Adjust inputs and try again."}


def error_remediation(status_code: int, failure_type: str = "") -> Dict[str, str]:
    if status_code == 401:
        return {"title": "Unauthorized", "hint": "Check API key or authentication settings.", "action": "Update the API key in Settings."}
    if status_code == 400:
        return {"title": "Bad request", "hint": "Review your inputs for validation errors.", "action": "Check the request payload and try again."}
    if status_code == 403:
        return {"title": "Forbidden", "hint": failure_type or "Action not permitted by policy/guardrails.", "action": "Review permissions/guardrail configuration."}
    if status_code == 404:
        return {"title": "Not found", "hint": "Resource does not exist or was not recorded yet.", "action": "Verify the ID and try again."}
    if status_code == 422:
        return {"title": "Unprocessable entity", "hint": "Schema validation failed.", "action": "Check required fields and types."}
    if status_code == 503:
        return {"title": "Service not ready", "hint": "API lifespan may not be started or a dependency is missing.", "action": "Start the API or check dependencies."}
    if status_code >= 500:
        return {"title": "Server error", "hint": "The service encountered an error.", "action": "Retry or check logs/traces."}
    return {"title": "Request failed", "hint": failure_type or "Unexpected error.", "action": "Try again or inspect the trace."}


def a11y_label(text: str) -> str:
    return text.strip()
