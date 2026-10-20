"""Shared rendering helpers for the Streamlit console (issue #40).

These helpers turn API payloads into readable UI, and — crucially — render API
failures using the failure taxonomy (``failure_type`` + ``failure_tags``) rather
than raw stack traces.
"""

from typing import Any, Dict

import streamlit as st

from ui.client import ApiResult


def api_base_url() -> str:
    return st.session_state.get("api_base_url", "http://localhost:8000")


def show_error(result: ApiResult) -> None:
    """Render a failed API call as a readable taxonomy-aware message."""
    if result.error:
        st.error(result.error)
        return
    failure_type = result.failure_type or "unknown_failure"
    tags = ", ".join(result.failure_tags) or "-"
    detail = result.data.get("error") or result.data.get("detail") or "Request failed"
    st.error(
        f"**{failure_type}** (HTTP {result.status_code})\n\n"
        f"{detail}\n\n"
        f"`failure_tags`: {tags}"
    )
    if result.request_id:
        st.caption(f"request_id: {result.request_id}")


def require_ok(result: ApiResult) -> bool:
    if result.ok:
        return True
    show_error(result)
    return False


def metric_rows(metrics: Dict[str, Any]) -> list:
    return [{"metric": key, "value": value} for key, value in (metrics or {}).items()]


def latency_rows(latency: Dict[str, Any]) -> list:
    rows = []
    for key, value in (latency or {}).items():
        if key.endswith("_ms"):
            continue
        rows.append({"stage": key, "latency_ms": value})
    return rows
