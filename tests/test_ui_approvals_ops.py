"""Tests for UX17 (#164): approvals queue operations and safe export."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import pytest

from ui.approvals import (
    AGE_FILTER_OPTIONS,
    ANY_VALUE,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SLA_CRITICAL_HOURS,
    DEFAULT_SLA_WARNING_HOURS,
    SORT_OPTIONS,
    age_label,
    age_seconds,
    approval_filter_options,
    approval_rows,
    bulk_confirmation_text,
    bulk_result_row,
    bulk_summary,
    export_csv,
    export_filename,
    export_json,
    filter_approval_records,
    paginate_approval_records,
    pending_ids,
    requester_value,
    select_pending_records,
    sla_bucket,
    sla_summary,
    sort_approval_records,
    tenant_value,
)
from ui.navigation import ALL_CAPABILITIES
from ui.workspace import (
    apply_workspace,
    empty_workspace,
    normalize_workspace,
    workspace_from_query_params,
    workspace_to_query_params,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
APPROVALS_PATH = REPO_BASE / "ui" / "approvals.py"
WORKSPACE_PATH = REPO_BASE / "ui" / "workspace.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"
SCREENS = [
    "Overview / Health",
    "Query Studio",
    "Compare (what-if)",
    "Evaluation",
    "Governance & Cost",
    "Guardrails",
    "Approvals",
    "Audit",
    "Access / RBAC",
    "Admin",
    "Traces",
    "Settings (read-only)",
]
ACCESS = {
    "ok": True,
    "enabled": True,
    "role": "admin",
    "capabilities": list(ALL_CAPABILITIES),
    "tenant": {"id": "tenant-a", "workspace": "workspace-a"},
}
NOW = 1_700_000_000.0

POLICIES_YAML = """
enabled: false
engine: cel
bundles: []
dry_run: false
hitl:
  enabled: true
  require_approval_for: ["pipeline_rebuild"]
"""


def _record(
    request_id: str,
    *,
    status: str = "pending",
    action: str = "pipeline_rebuild",
    created_at: float = NOW,
    decided_at: float | None = None,
    policy: Dict[str, Any] | None = None,
    context: Dict[str, Any] | None = None,
    reason: str = "review",
) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "status": status,
        "action": action,
        "reason": reason,
        "created_at": created_at,
        "decided_at": decided_at,
        "policy": policy or {"policy_id": "p1", "bundle": "core", "action": action},
        "context": context or {},
    }


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {
            "response": f"echo:{query}",
            "failure_tags": [],
            "retrieved_docs": [],
            "retrieved_docs_with_scores": [],
            "cost": {"estimated_cost_usd": 0.0},
            "latency": {"total_ms": 1.0},
            "observability": {"status": "success"},
        }


@pytest.fixture()
def approvals_api(tmp_path, monkeypatch):
    pytest.importorskip("requests")
    from fastapi.testclient import TestClient

    import ui.client as client_module
    from app.main import create_app
    from core.services.approval import ApprovalService

    app = create_app(pipeline_builder=lambda **_ignored: _FakePipeline())
    test_client = TestClient(app)
    test_client.__enter__()
    policy_path = tmp_path / "policies.yaml"
    policy_path.write_text(POLICIES_YAML, encoding="utf-8")
    service = ApprovalService(
        config_path=str(policy_path), clock=lambda: NOW
    )
    pending = [
        service.create_request("pipeline_rebuild", context={"request_id": f"ctx-{i}"})
        for i in range(3)
    ]
    test_client.app.state.approvals = service

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        path = urlparse(url).path
        return test_client.request(method, path, headers=headers or {}, **kwargs)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    client = client_module.ApiClient(base_url="http://testserver")
    yield client, service, pending
    test_client.__exit__(None, None, None)


def test_requester_and_tenant_fallbacks_are_redacted():
    record = {
        "requester": "alice",
        "context": {
            "tenant_id": "tenant-a",
            "workspace": "ws-1",
            "app": "console",
            "owner": "Bearer abcdefghijkl",
        },
    }
    assert requester_value(record) == "alice"
    assert tenant_value(record) == "tenant-a"
    rows = approval_rows([record], NOW)
    assert rows[0]["requester"] == "alice"
    assert rows[0]["tenant"] == "tenant-a"
    assert rows[0]["workspace"] == "ws-1"
    assert rows[0]["app"] == "console"


def test_filter_options_and_combined_queue_filters():
    records = [
        _record(
            "a",
            policy={"policy_id": "p1", "bundle": "core", "action": "pipeline_rebuild"},
            context={"requester": "alice", "tenant": "t1"},
            reason="rotate key",
        ),
        _record(
            "b",
            status="approved",
            action="model_swap",
            policy={"policy_id": "p2", "bundle": "models", "action": "model_swap"},
            context={"requester": "bob", "tenant": "t2"},
            reason="already approved",
        ),
        _record(
            "c",
            policy={"policy_id": "p1", "bundle": "core", "action": "pipeline_rebuild"},
            context={"requester": "alice", "tenant": "t1"},
            reason="urgent rotation",
        ),
    ]
    options = approval_filter_options(records)
    assert options["actions"] == ["model_swap", "pipeline_rebuild"]
    assert options["policies"] == ["core", "models", "p1", "p2"]
    assert options["requesters"] == ["alice", "bob"]
    assert options["tenants"] == ["t1", "t2"]

    assert [r["request_id"] for r in filter_approval_records(records, status="pending")] == [
        "a",
        "c",
    ]
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", action="model_swap")
    ] == ["b"]
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", policy="p1")
    ] == ["a", "c"]
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", requester="bob")
    ] == ["b"]
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", tenant="t1")
    ] == ["a", "c"]
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", search="urgent")
    ] == ["c"]
    assert [
        r["request_id"]
        for r in filter_approval_records(
            records, status="pending", action="pipeline_rebuild", search="rotate"
        )
    ] == ["a"]


def test_age_sla_thresholds_and_labels():
    records = [
        _record("ok", created_at=NOW - 3600),
        _record("warning", created_at=NOW - 5 * 3600),
        _record("critical", created_at=NOW - 30 * 3600),
        _record(
            "decided",
            status="approved",
            created_at=NOW - 10_000,
            decided_at=NOW - 9_000,
        ),
    ]
    assert age_seconds(records[3], NOW) == 1_000
    assert sla_bucket(records[0], NOW) == "ok"
    assert sla_bucket(records[1], NOW) == "warning"
    assert sla_bucket(records[2], NOW) == "critical"
    assert sla_bucket(records[3], NOW) == "decided"
    assert sla_bucket({"status": "pending"}, NOW) == "unknown"
    assert age_label(30) == "<1m"
    assert age_label(3_660) == "1h 1m"
    assert age_label(90_000) == "1d 1h"
    assert age_label(None) == ""
    assert sla_summary(records, NOW) == {
        "ok": 1,
        "warning": 1,
        "critical": 1,
        "decided": 1,
        "unknown": 0,
    }
    assert [
        r["request_id"]
        for r in filter_approval_records(records, status="all", age="> 4 hours", now=NOW)
    ] == ["warning", "critical"]


def test_sort_orders_are_deterministic():
    records = [
        _record("b", created_at=NOW - 2_000),
        _record("a", created_at=NOW - 2_000),
        _record("new", created_at=NOW - 1_000),
        _record("old", created_at=NOW - 3_000),
    ]
    assert [r["request_id"] for r in sort_approval_records(records, "Newest first", NOW)] == [
        "new",
        "a",
        "b",
        "old",
    ]
    assert [r["request_id"] for r in sort_approval_records(records, "Oldest first", NOW)] == [
        "old",
        "a",
        "b",
        "new",
    ]
    assert [
        r["request_id"]
        for r in sort_approval_records(records, "Longest pending first", NOW)
    ] == ["old", "a", "b", "new"]
    assert [
        r["request_id"]
        for r in sort_approval_records(records, "Shortest pending first", NOW)
    ] == ["new", "a", "b", "old"]
    assert [r["request_id"] for r in sort_approval_records(records, "bogus", NOW)] == [
        "new",
        "a",
        "b",
        "old",
    ]


def test_pagination_clamps_and_reports_bounds():
    records = [_record(str(i)) for i in range(5)]
    page = paginate_approval_records(records, page=99, page_size=2)
    assert page == {
        "items": [records[4]],
        "page": 3,
        "page_size": 2,
        "total": 5,
        "pages": 3,
        "start": 4,
        "end": 5,
        "has_prev": True,
        "has_next": False,
    }
    first = paginate_approval_records(records, page=0, page_size=2)
    assert first["page"] == 1
    assert first["has_prev"] is False
    empty = paginate_approval_records([], page=4, page_size=10)
    assert empty["pages"] == 0
    assert empty["page"] == 1
    assert empty["items"] == []
    assert empty["has_next"] is False
    invalid = paginate_approval_records(records, page="x", page_size="y")
    assert invalid["page_size"] == DEFAULT_PAGE_SIZE


def test_approval_rows_include_age_sla_and_redacted_metadata():
    record = _record(
        "req-1",
        created_at=NOW - 5 * 3600,
        reason="token sk-secret-value",
        context={"requester": "alice", "tenant": "t1"},
    )
    row = approval_rows([record], NOW)[0]
    assert row["age"] == "5h"
    assert row["age_seconds"] == 18_000
    assert row["sla"] == "Warning"
    assert row["requester"] == "alice"
    assert row["tenant"] == "t1"
    assert "sk-secret-value" not in row["reason"]
    assert SLA_LABELS_OK(row)


def SLA_LABELS_OK(row: Dict[str, Any]) -> bool:
    return row["sla"] in ("OK", "Warning", "Critical", "Decided", "Unknown")


def test_safe_export_excludes_raw_context_and_secrets():
    record = _record(
        "req-1",
        action="=SUM(1,1)",
        reason="token sk-leak",
        context={
            "api_key": "sk-super-secret",
            "password": "hunter2",
            "trace_id": "trace-1",
            "audit_request_id": "audit-1",
        },
        policy={"policy_id": "p1", "bundle": "core", "action": "pipeline_rebuild"},
    )
    payload = json.loads(export_json([record], NOW))
    assert payload["count"] == 1
    row = payload["approvals"][0]
    assert "context" not in row
    assert "api_key" not in row
    assert "sk-" not in json.dumps(payload)
    assert "hunter2" not in json.dumps(payload)
    assert row["evidence_ids"] == "trace_id=trace-1; audit_request_id=audit-1"
    assert row["requester"] == ""
    text = export_csv([record], NOW)
    assert text.startswith("request_id,status,action")
    assert "hunter2" not in text
    assert "sk-" not in text
    assert "'=SUM(1,1)" in text
    assert export_filename("json", NOW).endswith(".json")


def test_bulk_selection_only_pending_and_deduped():
    records = [
        _record("a"),
        _record("b", status="approved"),
        _record("c"),
        _record("c"),
    ]
    assert pending_ids(records) == ["a", "c"]
    selected = select_pending_records(records, ["c", "b", "c", "missing"])
    assert [r["request_id"] for r in selected] == ["c"]
    assert "one at a time" in bulk_confirmation_text(2, "approved")
    assert "not rolled back" in bulk_confirmation_text(2, "rejected")
    assert "Select at least one" in bulk_confirmation_text(0, "approved")


def test_bulk_results_and_partial_failure_summary():
    rows = [
        bulk_result_row("a", "approved", ok=True, status="approved"),
        bulk_result_row(
            "b",
            "approved",
            ok=False,
            failure_type="approval_not_found",
            error="token sk-leak",
        ),
        bulk_result_row("c", "approved", ok=True, status="rejected"),
    ]
    assert rows[0]["outcome"] == "succeeded"
    assert rows[1]["outcome"] == "failed"
    assert "sk-leak" not in rows[1]["detail"]
    assert rows[2]["detail"] == "server status: rejected"
    summary = bulk_summary(rows)
    assert summary["total"] == 3
    assert summary["succeeded"] == 2
    assert summary["failed"] == 1
    assert summary["failed_ids"] == ["b"]


def test_workspace_round_trips_extended_approval_filters():
    workspace = normalize_workspace(
        {
            "screen": "Approvals",
            "approvals": {
                "status": "all",
                "request_id": "req-42",
                "action": "pipeline_rebuild",
                "policy": "p1",
                "requester": "alice",
                "tenant": "t1",
                "age": "> 4 hours",
                "search": "urgent",
                "sort": "Longest pending first",
                "page": 2,
                "page_size": 50,
                "warning_hours": 2,
                "critical_hours": 8,
            },
        }
    )
    params = workspace_to_query_params(workspace, include_blob=False)
    assert params["approval_action"] == "pipeline_rebuild"
    assert params["approval_policy"] == "p1"
    assert params["approval_requester"] == "alice"
    assert params["approval_tenant"] == "t1"
    assert params["approval_age"] == "> 4 hours"
    assert params["approval_search"] == "urgent"
    assert params["approval_sort"] == "Longest pending first"
    assert params["approval_page"] == "2"
    assert params["approval_page_size"] == "50"
    assert params["approval_warning_hours"] == "2.0"
    assert params["approval_critical_hours"] == "8.0"
    restored = workspace_from_query_params(params)
    assert restored["approvals"] == workspace["approvals"]

    state: Dict[str, Any] = {}
    assert apply_workspace(workspace, state, ACCESS, SCREENS) == "Approvals"
    assert state["approval_action"] == "pipeline_rebuild"
    assert state["approval_policy"] == "p1"
    assert state["approval_requester"] == "alice"
    assert state["approval_tenant"] == "t1"
    assert state["approval_age"] == "> 4 hours"
    assert state["approval_search"] == "urgent"
    assert state["approval_sort"] == "Longest pending first"
    assert state["approval_page"] == 2
    assert state["approval_page_size"] == 50
    assert state["approval_warning_hours"] == 2.0
    assert state["approval_critical_hours"] == 8.0
    assert state["approval_bulk_ids"] == []

    defaults = empty_workspace()["approvals"]
    assert defaults["action"] == ANY_VALUE
    assert defaults["age"] == AGE_FILTER_OPTIONS[0]
    assert defaults["sort"] == SORT_OPTIONS[0]
    assert defaults["page_size"] == DEFAULT_PAGE_SIZE
    assert defaults["warning_hours"] == DEFAULT_SLA_WARNING_HOURS
    assert defaults["critical_hours"] == DEFAULT_SLA_CRITICAL_HOURS

    clamped = normalize_workspace(
        {"approvals": {"warning_hours": 10, "critical_hours": 1}}
    )["approvals"]
    assert clamped["critical_hours"] == 10.0


def test_approvals_screen_wires_queue_operations():
    source = APP_PATH.read_text(encoding="utf-8")
    for token in (
        '"Queue filters"',
        '"Bulk decisions"',
        '"SLA warning (hours)"',
        "approval_filter_options(",
        "filter_approval_records(",
        "sort_approval_records(",
        "paginate_approval_records(",
        "bulk_confirmation_text(",
        "bulk_result_row(",
        "bulk_summary(",
        "export_json(",
        "export_csv(",
        "st.download_button(",
        "api.decide_approval(",
        "approval_bulk_confirm",
        '_render_saved_views("approvals")',
    ):
        assert token in source


def test_approval_helpers_remain_http_only():
    for path in (APPROVALS_PATH, WORKSPACE_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith(("app.", "core.")) for alias in node.names
                )
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("app.", "core."))


def test_tour_mentions_queue_operations():
    source = TOUR_PATH.read_text(encoding="utf-8")
    assert "SLA" in source
    assert "bulk" in source.lower()
    assert "export" in source.lower()


def test_client_sequential_bulk_decisions_and_partial_failure(approvals_api):
    client, _service, pending = approvals_api
    assert len(pending) == 3
    rows = []
    for request in pending:
        result = client.decide_approval(
            request.request_id, "approved", decided_by="alice", note="bulk"
        )
        rows.append(
            bulk_result_row(
                request.request_id,
                "approved",
                ok=result.ok,
                status=result.data.get("status") or "",
            )
        )
    missing = client.decide_approval("missing-request", "approved")
    rows.append(
        bulk_result_row(
            "missing-request",
            "approved",
            ok=missing.ok,
            failure_type=missing.failure_type or "",
            error=missing.error or "",
        )
    )
    assert bulk_summary(rows) == {
        "total": 4,
        "succeeded": 3,
        "failed": 1,
        "failed_ids": ["missing-request"],
    }
    assert client.approvals(status="pending").data["count"] == 0
    assert client.approvals(status="approved").data["count"] == 3
