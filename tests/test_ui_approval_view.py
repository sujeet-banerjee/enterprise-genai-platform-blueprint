"""Structured approvals presentation tests (#249)."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui import approval_view

NOW = 1_800_000.0

RECORD = {
    "request_id": "apr-2f91",
    "status": "pending",
    "action": "pipeline_rebuild",
    "reason": "Canary model promotion",
    "created_at": NOW - 6 * 3600,
    "context": {
        "requester": "alice",
        "tenant": "tenant-a",
        "workspace": "ws-1",
        "app": "console",
        "trace_id": "trace-7c2a",
        "run_id": "run-42",
    },
    "policy": {
        "policy_id": "p-hitl-01",
        "bundle": "production",
        "action": "pipeline_rebuild",
    },
}


def test_request_summary_view_uses_approval_rows_and_badges() -> None:
    view = approval_view.request_summary_view(RECORD, now=NOW)
    assert len(view["kpis"]) == 5
    assert [kpi["label"] for kpi in view["kpis"]] == [
        "Status", "SLA", "Action", "Requester", "Tenant"
    ]
    assert view["kpis"][0]["status"]["tone"] == "warning"
    assert view["kpis"][1]["status"]["tone"] == "warning"
    assert [row["label"] for row in view["rows"]] == [
        "Request Id", "Reason", "Created", "Age", "Policy", "Workspace", "App"
    ]
    assert "Approval request summary" in view["markdown"]
    assert "Pending" in view["markdown"]
    assert "Warning" in view["markdown"]
    assert "alice" in view["markdown"]
    assert "tenant-a" in view["markdown"]
    assert "pipeline_rebuild" in view["markdown"]


def test_request_summary_view_handles_empty_record() -> None:
    html = approval_view.request_summary_markdown({}, now=NOW)
    assert "Unknown" in html
    assert "genai-kpi-strip" in html
    assert "Request Id" in html


def test_flatten_metadata_bounds_rows_and_expands_lists() -> None:
    flat = approval_view.flatten_metadata(
        {"items": [1, {"token": "abc"}], "nested": {"trace": {"id": "t-1"}}},
        max_rows=5,
    )
    assert flat["items.0"] == 1
    assert flat["items.1.token"] == "abc"
    assert flat["nested.trace.id"] == "t-1"
    bounded = approval_view.flatten_metadata(
        {f"key-{index}": index for index in range(20)}, max_rows=5
    )
    assert len(bounded) == 5


def test_context_policy_panels_flatten_nested_and_redact_secrets() -> None:
    panels = approval_view.context_policy_panels(
        {
            "context": {
                "trace": {"id": "t-1"},
                "api_key": "sk-should-not-leak",
                "note": "<script>alert(1)</script>",
            },
            "policy": {"bundle": "production", "labels": ["pii", "hitl"]},
        }
    )
    assert "Trace.Id" in panels["context"]
    assert "t-1" in panels["context"]
    assert "Api Key" in panels["context"]
    assert "[REDACTED]" in panels["context"]
    assert "&lt;script&gt;" in panels["context"]
    assert "<script>" not in panels["context"]
    assert "production" in panels["policy"]
    assert "Labels.0" in panels["policy"]


def test_evidence_chips_markdown_links_to_traces_and_audit() -> None:
    html = approval_view.evidence_chips_markdown(
        [
            {"kind": "trace_request_id", "value": "trace-1"},
            {"kind": "audit_request_id", "value": "audit-1"},
            {"kind": "run_id", "value": "run-1"},
        ]
    )
    assert "genai-evidence-chips" in html
    links = [unescape(match) for match in re.findall(r'href="([^"]+)"', html)]
    queries = [parse_qs(urlsplit(link).query) for link in links]
    assert queries[0] == {"screen": ["Traces"], "traces_request_id": ["trace-1"]}
    assert queries[1] == {"screen": ["Audit"], "audit_request": ["audit-1"]}
    assert queries[2] == {"screen": ["Traces"], "traces_request_id": ["run-1"]}
    assert "No correlation ids recorded." in approval_view.evidence_chips_markdown([])


def test_decision_history_markdown_structures_entries_and_escapes() -> None:
    html = approval_view.decision_history_markdown(
        {
            "context": {
                "decisions": [
                    {"decision": "approved", "decided_by": "alice", "note": "<img src=x>"}
                ]
            }
        }
    )
    assert "genai-decision-history" in html
    assert "Decision 1: approved" in html
    assert "alice" in html
    assert "&lt;img src=x&gt;" in html
    assert "<img" not in html
    assert "No decision history recorded yet." in approval_view.decision_history_markdown({})


def test_approval_detail_view_returns_redacted_panels() -> None:
    view = approval_view.approval_detail_view(
        {
            **RECORD,
            "api_key": "sk-approval-secret",
            "context": {**RECORD["context"], "authorization": "Bearer abc.def"},
        },
        now=NOW,
    )
    assert set(view) == {"summary", "context", "policy", "evidence", "decisions", "raw"}
    assert view["raw"]["api_key"] == "[REDACTED]"
    assert view["raw"]["context"]["authorization"] == "[REDACTED]"
    assert "sk-approval-secret" not in str(view)
    assert "Bearer abc.def" not in str(view)


def test_decision_confirmation_view_validates_and_mentions_payload() -> None:
    view = approval_view.decision_confirmation_view(
        RECORD, "approved", "bob", "canary approved"
    )
    assert view["decision"] == "approved"
    assert "Confirm approved" in view["markdown"]
    assert "bob" in view["markdown"]
    assert "canary approved" in view["markdown"]
    assert "Single request" in view["markdown"]
    assert "No - the decision is audited" in view["markdown"]
    invalid = approval_view.decision_confirmation_markdown(RECORD, "maybe")
    assert "Confirm invalid" in invalid


def test_approval_view_helpers_are_pure() -> None:
    source = Path("ui/approval_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_approval_detail_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_approvals")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "approval_detail_view(" in body
    assert "decision_confirmation_markdown(" in body
    assert 'st.json(detail_view["raw"])' in body
    assert "approval_decision_confirm_" in body
    assert "disabled=not confirm_decision" in body
    assert "st.json(record.get(\"context\")" not in body
    assert "st.json(policy)" not in body
    assert "_render_approval_decisions" not in source


def test_approval_view_wireframe_and_theme_are_indexed() -> None:
    assert Path("docs/wireframes/249-approvals-view.excalidraw").is_file()
    assert Path("docs/wireframes/249-approvals-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "249-approvals-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-evidence-chips" in theme
    assert "genai-decision-history" in theme
