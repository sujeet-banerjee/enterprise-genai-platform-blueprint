"""Tests for UX16 (#163): HTTP-only HITL approvals console."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import pytest

from ui.approvals import (
    approval_rows,
    can_decide,
    decision_payload,
    deep_link_params,
    evidence_links,
    format_timestamp,
    normalize_status,
    policy_summary,
    redact_approval,
    status_filter,
    summary_counts,
)
from ui.navigation import ALL_CAPABILITIES, NAV_GROUPS, QUICK_ACTIONS, SCREEN_CAPABILITIES
from ui.workspace import (
    apply_workspace,
    empty_workspace,
    normalize_workspace,
    workspace_from_query_params,
    workspace_from_session,
    workspace_to_query_params,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"
APPROVALS_PATH = REPO_BASE / "ui" / "approvals.py"
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

POLICIES_YAML = """
enabled: false
engine: cel
bundles: []
dry_run: false
hitl:
  enabled: true
  require_approval_for: ["pipeline_rebuild"]
"""


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
    """Real approval API behind the HTTP-only ApiClient transport."""
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
    service = ApprovalService(config_path=str(policy_path), clock=lambda: 1_700_000_000.0)
    pending = service.create_request(
        "pipeline_rebuild",
        context={
            "request_id": "req-backend-1",
            "trace_id": "trace-1",
            "audit_request_id": "audit-1",
            "api_key": "sk-super-secret",
            "nested": {"span_id": "span-1"},
        },
        reason="would change the active model",
    )
    approved = service.create_request(
        "model_swap", context={"request_id": "req-backend-2"}, reason="already reviewed"
    )
    service.decide(approved.request_id, "approved", decided_by="reviewer", note="ok")
    test_client.app.state.approvals = service

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        path = urlparse(url).path
        return test_client.request(method, path, headers=headers or {}, **kwargs)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    client = client_module.ApiClient(base_url="http://testserver")
    yield client, service, pending, approved, test_client
    test_client.__exit__(None, None, None)


def _ast_screen_names():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SCREENS":
                    return [key.value for key in node.value.keys]
    raise AssertionError("SCREENS dict literal not found")


def test_approval_helpers_normalize_status_and_counts():
    assert normalize_status(None) == "pending"
    assert normalize_status(" APPROVED ") == "approved"
    assert normalize_status("bogus") == "pending"
    assert status_filter("all") is None
    assert status_filter("rejected") == "rejected"
    records = [
        {"status": "pending"},
        {"status": "approved"},
        {"status": "rejected"},
        {"status": "unexpected"},
    ]
    assert summary_counts(records) == {
        "total": 4,
        "pending": 1,
        "approved": 1,
        "rejected": 1,
        "other": 1,
    }


def test_approval_rows_redact_and_summarize_policy():
    rows = approval_rows(
        [
            {
                "request_id": "req-1",
                "status": "pending",
                "action": "pipeline_rebuild",
                "reason": "token sk-secret-value",
                "policy": {"policy_id": "p1", "bundle": "core", "labels": ["hitl"]},
                "created_at": 1_700_000_000,
                "decided_by": "Bearer abcdefghijkl",
            }
        ]
    )
    assert rows[0]["request_id"] == "req-1"
    assert "sk-secret-value" not in rows[0]["reason"]
    assert "[REDACTED]" in rows[0]["reason"]
    assert rows[0]["policy"] == "policy_id=p1 | bundle=core | labels=hitl"
    assert rows[0]["created"].endswith("UTC")
    assert "Bearer" not in rows[0]["decided_by"]


def test_redact_approval_masks_nested_secret_keys_and_values():
    payload = {
        "api_key": "sk-very-secret",
        "context": {
            "password": "hunter2",
            "note": "Authorization: Bearer abcdefghijklmnop",
            "items": [{"client_secret": "hidden"}],
        },
    }
    redacted = redact_approval(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["context"]["password"] == "[REDACTED]"
    assert "Bearer" not in redacted["context"]["note"]
    assert redacted["context"]["items"][0]["client_secret"] == "[REDACTED]"


def test_evidence_links_collects_nested_ids_without_duplicates():
    record = {
        "context": {
            "request_id": "req-1",
            "nested": {"trace_id": "trace-1", "span_id": "span-1"},
            "list": [{"run_id": "run-1"}],
        },
        "policy": {"audit_request_id": "audit-1"},
    }
    rows = evidence_links(record)
    assert {(row["kind"], row["value"]) for row in rows} == {
        ("request_id", "req-1"),
        ("trace_id", "trace-1"),
        ("span_id", "span-1"),
        ("run_id", "run-1"),
        ("audit_request_id", "audit-1"),
    }


def test_decision_payload_and_can_decide():
    with pytest.raises(ValueError):
        decision_payload("maybe")
    payload = decision_payload(" APPROVED ", " reviewer ", "note sk-secret")
    assert payload["decision"] == "approved"
    assert payload["decided_by"] == "reviewer"
    assert payload["note"] == "note [REDACTED]"
    assert can_decide({"status": "pending"})
    assert not can_decide({"status": "approved"})
    assert not can_decide(None)


def test_deep_link_and_timestamp_helpers():
    assert deep_link_params("req:1") == {
        "screen": "Approvals",
        "approval_request": "req:1",
    }
    assert deep_link_params("") == {}
    assert format_timestamp(0) == "1970-01-01 00:00:00 UTC"
    assert format_timestamp(None) == ""
    assert policy_summary({"policy_id": "p", "labels": ["a"]}) == "policy_id=p | labels=a"


def test_workspace_round_trips_approval_deep_links():
    workspace = normalize_workspace(
        {
            "screen": "Approvals",
            "approvals": {"status": "approved", "request_id": "req-42"},
        }
    )
    params = workspace_to_query_params(workspace, include_blob=False)
    assert params["screen"] == "Approvals"
    assert params["approval_status"] == "approved"
    assert params["approval_request"] == "req-42"
    restored = workspace_from_query_params(params)
    assert restored["approvals"]["status"] == "approved"
    assert restored["approvals"]["request_id"] == "req-42"

    state: Dict[str, Any] = {}
    screen = apply_workspace(workspace, state, ACCESS, SCREENS)
    assert screen == "Approvals"
    assert state["approval_status"] == "approved"
    assert state["approval_request_id"] == "req-42"

    from_session = workspace_from_session(
        {"active_screen": "Approvals", "approval_status": "rejected", "approval_request_id": "req-9"}
    )
    assert from_session["approvals"]["status"] == "rejected"
    assert from_session["approvals"]["request_id"] == "req-9"
    assert empty_workspace()["approvals"]["status"] == "pending"
    assert empty_workspace()["approvals"]["request_id"] == ""


def test_client_lists_filters_and_gets_approvals(approvals_api):
    client, _service, pending, approved, _test_client = approvals_api
    all_result = client.approvals()
    assert all_result.ok
    assert all_result.data["enabled"] is True
    assert all_result.data["count"] == 2
    assert {item["request_id"] for item in all_result.data["requests"]} == {
        pending.request_id,
        approved.request_id,
    }
    pending_result = client.approvals(status="pending")
    assert pending_result.ok
    assert pending_result.data["count"] == 1
    assert pending_result.data["requests"][0]["request_id"] == pending.request_id
    all_alias = client.approvals(status="all")
    assert all_alias.data["count"] == 2

    detail = client.approval(pending.request_id)
    assert detail.ok
    assert detail.data["status"] == "pending"
    assert detail.data["context"]["api_key"] == "sk-super-secret"

    missing = client.approval("does-not-exist")
    assert not missing.ok
    assert missing.status_code == 404
    assert missing.failure_type == "approval_not_found"


def test_client_submits_decision_and_updates_queue(approvals_api):
    client, _service, pending, _approved, _test_client = approvals_api
    result = client.decide_approval(
        pending.request_id, "rejected", decided_by="alice", note="too risky"
    )
    assert result.ok
    assert result.data["status"] == "rejected"
    assert result.data["decided_by"] == "alice"
    assert result.data["decision_note"] == "too risky"

    pending_result = client.approvals(status="pending")
    assert pending_result.data["count"] == 0
    detail = client.approval(pending.request_id)
    assert detail.data["status"] == "rejected"
    assert can_decide(detail.data) is False


def test_client_reports_disabled_and_missing_service(approvals_api, tmp_path):
    client, _service, _pending, _approved, test_client = approvals_api
    from core.services.approval import ApprovalService

    disabled_path = tmp_path / "disabled.yaml"
    disabled_path.write_text("hitl:\n  enabled: false\n", encoding="utf-8")
    test_client.app.state.approvals = ApprovalService(config_path=str(disabled_path))
    disabled = client.approvals()
    assert disabled.ok
    assert disabled.data["enabled"] is False

    del test_client.app.state.approvals
    missing = client.approvals()
    assert not missing.ok
    assert missing.status_code == 503
    assert missing.failure_type == "not_ready"


def test_approvals_screen_is_registered_and_http_only():
    source = APP_PATH.read_text(encoding="utf-8")
    assert '"Approvals": screen_approvals' in source
    for token in (
        "api.approvals(",
        "api.approval(",
        "api.decide_approval(",
        "redact_approval(",
        "evidence_links(",
        '_render_saved_views("approvals")',
    ):
        assert token in source
    assert "Approvals" in _ast_screen_names()
    assert SCREEN_CAPABILITIES["Approvals"] == "approve"
    assert "approve" in ALL_CAPABILITIES
    assert any("Approvals" in group.screens for group in NAV_GROUPS)
    assert any(action.screen == "Approvals" for action in QUICK_ACTIONS)

    tree = ast.parse(APPROVALS_PATH.read_text(encoding="utf-8"), filename=str(APPROVALS_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith(("app.", "core.")) for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("app.", "core."))


def test_tour_mentions_approvals():
    source = TOUR_PATH.read_text(encoding="utf-8")
    assert 'screen="Approvals"' in source
    assert "10. Approvals (HITL)" in source
