"""Tests for the async operations console slice (#280)."""

import ast
from pathlib import Path
from typing import Any, Dict

import pytest

from ui.client import ApiClient
from ui.journeys import DEMO_RESULT, demo_fixture
from ui.operations import (
    ensure_client_session,
    format_operation_time,
    is_active_operation,
    is_terminal_operation,
    normalize_operation,
    operation_failure,
    operation_result,
    operations_summary,
    operations_table_markdown,
    pending_operation_markdown,
)

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "ui" / "app.py"
CLIENT = REPO / "ui" / "client.py"


class _FakeResponse:
    status_code = 200
    headers: Dict[str, str] = {}
    text = "{}"

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload

    def json(self) -> Dict[str, Any]:
        return self.payload


def _capture_requests(monkeypatch: pytest.MonkeyPatch, payload: Dict[str, Any]) -> Dict[str, Any]:
    calls: Dict[str, Any] = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        calls.update(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "timeout": timeout,
                "kwargs": kwargs,
            }
        )
        return _FakeResponse(payload)

    monkeypatch.setattr("ui.client.requests.request", fake_request)
    return calls


def test_ensure_client_session_is_stable_and_unique() -> None:
    state: Dict[str, Any] = {}
    first = ensure_client_session(state)
    assert first.startswith("ui-")
    assert ensure_client_session(state) == first
    assert ensure_client_session({}) != first


def test_normalize_operation_defaults_and_status_helpers() -> None:
    queued = normalize_operation({"id": "op-1", "progress": {"stage": "embedding"}})
    assert queued["status"] == "queued"
    assert queued["stage"] == "embedding"
    assert queued["request_id"] == "op-1"
    assert is_active_operation(queued)
    assert not is_terminal_operation(queued)
    assert is_terminal_operation(normalize_operation({"status": "CANCELLED"}))


def test_operation_result_and_failure_are_detached_and_escaped() -> None:
    source = {
        "id": "op-2",
        "status": "failed",
        "result": {"response": "answer"},
        "error": "denied",
        "failure_type": "guardrail_input_blocked",
        "failure_tags": ["injection"],
    }
    result = operation_result(source)
    result["response"] = "mutated"
    assert source["result"]["response"] == "answer"
    assert operation_result(source)["request_id"] == "op-2"
    assert operation_failure(source) == {
        "request_id": "op-2",
        "error": "denied",
        "failure_type": "guardrail_input_blocked",
        "failure_tags": ["injection"],
    }


def test_operations_summary_counts_include_experiments() -> None:
    operations = [
        {"id": "a", "kind": "query", "status": "running"},
        {"id": "b", "kind": "query", "status": "completed"},
        {"id": "c", "kind": "query", "status": "failed"},
        {"id": "d", "kind": "experiment", "status": "queued"},
    ]
    assert operations_summary(operations) == {
        "total": 4,
        "active": 2,
        "completed": 1,
        "failed": 1,
        "experiments": 1,
    }


def test_operations_table_escapes_ids_and_shows_empty_state() -> None:
    table = operations_table_markdown([{"id": "<script>alert(1)</script>", "status": "running"}])
    assert "<script>" not in table
    assert "&lt;script&gt;" in table
    assert "genai-table-scroll" in table
    assert "No operations" in operations_table_markdown([])


def test_pending_markdown_shows_request_id() -> None:
    body = pending_operation_markdown({"id": "op-3", "status": "queued"})
    assert "op-3" in body
    assert "queued" in body
    assert "genai-card--pending" in body


def test_format_operation_time_handles_bad_values() -> None:
    assert format_operation_time(0) == "1970-01-01 00:00:00 UTC"
    assert format_operation_time("not-a-time") == "-"


def test_client_sends_client_session_header(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_requests(monkeypatch, {"id": "op-4"})
    result = ApiClient(client_session="ui-session").submit_query_operation(
        "what is RAG?", top_k=2
    )
    assert result.ok
    assert calls["headers"]["X-Client-Session"] == "ui-session"
    assert calls["method"] == "POST"
    assert calls["url"].endswith("/v1/operations/query")
    assert calls["kwargs"]["json"] == {
        "query": "what is RAG?",
        "top_k": 2,
        "include_trace": True,
    }


def test_client_operations_are_always_owner_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_requests(monkeypatch, {"operations": []})
    assert ApiClient().operations(status="running", limit=10).ok
    assert calls["method"] == "GET"
    assert calls["url"].endswith("/v1/operations")
    assert calls["kwargs"]["params"]["mine"] is True
    assert calls["kwargs"]["params"]["status"] == "running"
    assert calls["kwargs"]["params"]["limit"] == 10


def test_demo_fixture_covers_async_operations_without_http() -> None:
    submitted = demo_fixture("/v1/operations/query", "POST", {"query": "demo"})
    listed = demo_fixture("/v1/operations")
    polled = demo_fixture(f"/v1/operations/{submitted['id']}")
    assert submitted["status"] == "completed"
    assert submitted["result"]["response"] == DEMO_RESULT["response"]
    assert any(item["kind"] == "experiment" for item in listed["operations"])
    assert polled["id"] == submitted["id"]


def test_app_and_client_expose_async_operations_wiring() -> None:
    app_tree = ast.parse(APP.read_text(encoding="utf-8"))
    client_tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    app_functions = {
        node.name for node in ast.walk(app_tree) if isinstance(node, ast.FunctionDef)
    }
    client_functions = {
        node.name for node in ast.walk(client_tree) if isinstance(node, ast.FunctionDef)
    }
    assert {"submit_query_operation", "operation", "operations"} <= client_functions
    assert {
        "_render_async_operation",
        "_render_async_operation_body",
        "_finalize_async_operation",
        "_render_operations_panel",
        "_operations_panel_body",
    } <= app_functions
    source = APP.read_text(encoding="utf-8")
    assert "submit_query_operation(" in source
    assert "_render_operations_panel(api)" in source
    assert "st.fragment" in source


def test_ui_remains_http_only() -> None:
    for path in (REPO / "ui").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.")
                assert not node.module.startswith("core.")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app.")
                    assert not alias.name.startswith("core.")
