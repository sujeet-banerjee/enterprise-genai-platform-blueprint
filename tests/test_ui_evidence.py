"""UX11: cross-object evidence helpers and wiring (#154)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict

from ui import evidence
from ui import workspace as ws


def _trace(rid: str = "req-1", **overrides: Any) -> Dict[str, Any]:
    trace: Dict[str, Any] = {
        "request_id": rid,
        "status": "success",
        "tenant": "tenant-a",
        "workspace": "ws",
        "app": "console",
        "attribution": {"user": "alice"},
        "latency": {
            "total_ms": 120.0,
            "stages": {
                "embedding": {"ms": 10.0},
                "retrieval": {"ms": 30.0},
                "llm_generation": {"ms": 70.0},
            },
        },
        "retrieved_documents": [{"doc_id": 1}, {"doc_id": 2}],
        "top_k": 2,
        "token_budget": {"input_tokens_estimated": 500, "allowed_output_tokens": 120},
        "failure_tags": [],
        "cache_hit": False,
        "guardrail_decisions": [
            {"guardrail": "injection", "decision": "allow", "stage": "input"}
        ],
        "resilience": {
            "attempts": 1,
            "failovers": 0,
            "breaker_opens": 0,
            "served_by": "primary",
            "tags": [],
        },
        "otel": {"trace_id": "otel-1", "span_id": "span-1"},
    }
    trace.update(overrides)
    return trace


def test_request_id_validation() -> None:
    assert evidence.clean_request_id("  'req-1'\n") == "req-1"
    assert evidence.validate_request_id("") != ""
    assert evidence.validate_request_id("   ") != ""
    assert evidence.validate_request_id("bad id!") != ""
    assert evidence.validate_request_id("req-1") == ""
    assert evidence.validate_request_id("trace:abc/1") == ""
    assert len(evidence.clean_request_id("x" * 500)) == evidence.MAX_REQUEST_ID_CHARS


def test_parse_request_ids_dedupes_and_caps() -> None:
    assert evidence.parse_request_ids("a b,a\nc;") == ["a", "b", "c"]
    many = " ".join(f"req-{index}" for index in range(15))
    assert len(evidence.parse_request_ids(many)) == evidence.MAX_REQUEST_IDS
    assert evidence.parse_request_ids(None) == []


def test_lookup_links_targets_and_order() -> None:
    links = evidence.lookup_links("req-1")
    assert [link["target"] for link in links] == ["trace", "audit", "metrics", "governance"]
    assert links[0]["screen"] == evidence.TRACE_SCREEN
    assert links[1]["screen"] == evidence.AUDIT_SCREEN
    assert links[2]["screen"] == evidence.GOVERNANCE_SCREEN
    assert all(link["label"] and link["help"] for link in links)
    assert evidence.lookup_links("") == []


def test_trace_summary_and_stage_map() -> None:
    trace = _trace()
    stages = evidence.stage_map(trace)
    assert stages == {"embedding": 10.0, "retrieval": 30.0, "llm_generation": 70.0}
    summary = evidence.trace_summary(trace)
    assert summary["status"] == "success"
    assert summary["total_ms"] == 120.0
    assert summary["documents"] == 2
    assert summary["guardrail_total"] == 1
    assert summary["cost_usd"] is None
    assert summary["resilience_served_by"] == "primary"
    assert summary["otel_trace_id"] == "otel-1"
    assert summary["user"] == "alice"

    degraded = evidence.trace_summary(
        _trace(status=None, failure_tags=["retrieval_empty"])
    )
    assert degraded["status"] == "degraded"
    assert degraded["failure_tags"] == "retrieval_empty"


def test_guardrail_counts_and_signature() -> None:
    trace = _trace(
        guardrail_decisions=[
            {"guardrail": "injection", "decision": "block"},
            {"guardrail": "pii", "decision": "redact"},
            {"guardrail": "deny_list", "decision": "allow"},
        ]
    )
    assert evidence.guardrail_counts(trace) == {"total": 3, "blocks": 1, "redactions": 1}
    signature = evidence.guardrail_signature(trace)
    assert "injection:block" in signature and "pii:redact" in signature


def test_diff_traces_highlights_meaningful_changes() -> None:
    left = _trace()
    right = _trace(
        "req-2",
        status="error",
        failure_type="llm_failure",
        failure_tags=["provider_timeout"],
        latency={
            "total_ms": 200.0,
            "stages": {"embedding": {"ms": 10.0}, "retrieval": {"ms": 90.0}},
        },
        retrieved_documents=[{"doc_id": 1}],
        guardrail_decisions=[
            {"guardrail": "injection", "decision": "block"},
        ],
        cache_hit=True,
    )
    rows = evidence.diff_traces(left, right)
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["total latency (ms)"]["delta"] == 80.0
    assert by_metric["total latency (ms)"]["change"] == "changed"
    assert by_metric["stage latency: retrieval (ms)"]["delta"] == 60.0
    assert by_metric["documents retrieved"]["delta"] == -1
    assert by_metric["failure type"]["right"] == "llm_failure"
    assert by_metric["guardrail blocks"]["delta"] == 1
    assert by_metric["cache hit"]["right"] is True
    assert by_metric["cost (USD)"]["left"] == "n/a"
    assert by_metric["cost (USD)"]["highlight"] is False

    highlighted = {row["metric"] for row in evidence.changed_rows(rows)}
    assert "total latency (ms)" in highlighted
    assert "tenant" not in highlighted
    assert "app" not in highlighted


def test_changed_rows_ignores_scope_only_changes() -> None:
    rows = evidence.diff_traces(_trace(), _trace("req-2", tenant="tenant-b"))
    metrics = {row["metric"] for row in evidence.changed_rows(rows)}
    assert "tenant" not in metrics
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["tenant"]["change"] == "changed"
    assert by_metric["tenant"]["highlight"] is False


def test_cross_scope_notice() -> None:
    trace = _trace()
    assert evidence.cross_scope_notice(trace, "tenant-a") == ""
    assert evidence.cross_scope_notice(trace, "") == ""
    notice = evidence.cross_scope_notice(trace, "tenant-z")
    assert "tenant-a" in notice and "tenant-z" in notice


def test_audit_events_for_filters_and_limits() -> None:
    events = [
        {"request_id": "req-1", "event_type": "audit"},
        {"request_id": "req-2", "event_type": "governance"},
        {"request_id": "req-1", "event_type": "pii"},
        {"event_type": "config"},
    ]
    matched = evidence.audit_events_for(events, "req-1")
    assert [event["event_type"] for event in matched] == ["audit", "pii"]
    assert len(evidence.audit_events_for(events, "req-1", limit=1)) == 1
    assert evidence.audit_events_for(events, "") == []
    assert evidence.audit_events_for(events, "missing") == []


def test_build_evidence_pack_redacts_and_allowlists() -> None:
    trace = _trace()
    metrics = {
        "totals": {"runs": 3, "api_key": "sk-leak"},
        "failures_by_type": {"llm_failure": 1},
        "guardrails": {"total_blocks": 1},
        "cost": {"total": 0.5},
        "unrelated": {"raw": "drop me"},
    }
    governance = {
        "enabled": True,
        "max_cost_per_request_usd": 0.1,
        "safety_margin_tokens": 64,
        "window": {"spend_usd": 1.0},
        "api_key": "sk-leak",
        "unrelated": {"raw": "drop me"},
    }
    events = [
        {"request_id": "req-1", "event_type": "audit"},
        {"request_id": "req-2", "event_type": "governance"},
    ]
    pack = evidence.build_evidence_pack(
        request_id="req-1",
        trace=trace,
        audit_events=events,
        metrics=metrics,
        governance=governance,
        comparison=evidence.changed_rows(evidence.diff_traces(trace, _trace("req-2"))),
        scope={"tenant": "tenant-a", "workspace": "ws"},
        generated_at="2026-01-01T00:00:00+00:00",
    )
    assert pack["schema"] == "genai-evidence-pack/v1"
    assert pack["redacted"] is True
    assert pack["request_id"] == "req-1"
    assert pack["scope"] == {"tenant": "tenant-a", "workspace": "ws"}
    assert pack["summary"]["documents"] == 2
    assert [event["event_type"] for event in pack["audit_events"]] == ["audit"]
    assert "unrelated" not in pack["metrics"]
    assert "unrelated" not in pack["governance"]
    assert pack["metrics"]["totals"]["api_key"] == "[REDACTED]"
    assert "api_key" not in pack["governance"]
    assert pack["comparison"] == []


def test_pack_scrubs_secret_values_in_strings() -> None:
    pack = evidence.build_evidence_pack(
        request_id="req-1",
        trace=_trace(note="token sk-abcdef123 and env:OPENAI_API_KEY"),
        metrics={"totals": {"note": "Bearer abcdefghijklmnop"}},
        governance={},
    )
    dumped = json.dumps(pack)
    assert "sk-abcdef123" not in dumped
    assert "env:OPENAI_API_KEY" not in dumped
    assert "abcdefghijklmnop" not in dumped
    assert "[REDACTED]" in dumped


def test_evidence_pack_markdown_and_filename() -> None:
    pack = evidence.build_evidence_pack(
        request_id="req-1",
        trace=_trace(),
        audit_events=[{"request_id": "req-1", "event_type": "audit", "outcome": "ok"}],
        metrics={"totals": {"runs": 1}},
        governance={"enabled": True},
        comparison=evidence.diff_traces(_trace(), _trace("req-2", status="error")),
    )
    markdown = evidence.evidence_pack_markdown(pack)
    assert markdown.startswith("# Evidence pack: req-1")
    assert "## Summary" in markdown
    assert "## Timeline" in markdown
    assert "## Audit events" in markdown
    assert "## Compare with another request" in markdown
    assert "Secrets, keys and raw configuration values are redacted" in markdown
    assert evidence.evidence_pack_filename("req-1") == "evidence-req-1.json"
    assert evidence.evidence_pack_filename("req/1 :x", "md") == "evidence-req-1-x.md"
    assert evidence.evidence_pack_filename("") == "evidence-request.json"


def test_workspace_roundtrip_evidence_fields() -> None:
    workspace = ws.empty_workspace()
    workspace["screen"] = "Traces"
    workspace["scope"] = {"tenant": "tenant-a", "workspace": "ws"}
    workspace["traces"] = {"request_id": "req-1", "compare_request_id": "req-2"}
    workspace["audit"] = {"limit": 50, "event_type": "", "request_id": "req-3"}
    workspace["governance"] = {
        "time_range": "Last hour",
        "tenant": "",
        "app": "",
        "user": "",
        "request_id": "req-4",
    }
    params = ws.workspace_to_query_params(workspace)
    assert params["request_id"] == "req-1"
    assert params["traces_compare"] == "req-2"
    assert params["audit_request"] == "req-3"
    assert params["gov_request"] == "req-4"

    restored = ws.workspace_from_query_params(params)
    assert restored["traces"]["request_id"] == "req-1"
    assert restored["traces"]["compare_request_id"] == "req-2"
    assert restored["audit"]["request_id"] == "req-3"
    assert restored["governance"]["request_id"] == "req-4"


def test_workspace_from_session_reads_evidence_state() -> None:
    state = {
        "active_screen": "Audit",
        "trace_request_id": "req-1",
        "trace_compare_request_id": "req-2",
        "audit_request_id": "req-3",
        "gov_request_id": "req-4",
    }
    workspace = ws.workspace_from_session(state)
    assert workspace["traces"] == {"request_id": "req-1", "compare_request_id": "req-2"}
    assert workspace["audit"]["request_id"] == "req-3"
    assert workspace["governance"]["request_id"] == "req-4"


def test_state_defaults_and_direct_params_cover_evidence() -> None:
    state: Dict[str, Any] = {}
    ws.ensure_state_defaults(state)
    assert state["trace_compare_request_id"] == ""
    assert state["trace_compare_autoload"] is False
    assert state["audit_request_id"] == ""
    assert state["gov_request_id"] == ""
    for param in ("traces_compare", "audit_request", "gov_request"):
        assert param in ws.DIRECT_PARAMS
    assert "traces_compare" in ws.MANAGED_PARAMS


def test_app_wiring_for_cross_object_evidence() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    for token in (
        "from ui.evidence import",
        "_open_evidence",
        "_render_evidence_links",
        "_render_evidence_pack",
        "_fetch_trace",
        "diff_traces",
        "changed_rows",
        "cross_scope_notice",
        "audit_events_for",
        "build_evidence_pack",
        "validate_request_id",
        "Compare requests",
        "Evidence pack",
        "Open trace for this request",
        "Evidence focus",
        "trace_compare_request_id",
    ):
        assert token in source, token
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"_open_evidence", "_render_evidence_links", "_render_evidence_pack"} <= functions
    assert {"screen_traces", "screen_audit", "screen_governance"} <= functions


def test_evidence_module_is_pure() -> None:
    source = Path("ui/evidence.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert "app" not in modules
    assert "core" not in modules
    assert "streamlit" not in modules
    assert "requests" not in modules


def test_evidence_helpers_handle_missing_trace_fields() -> None:
    empty: Dict[str, Any] = {}
    assert evidence.stage_map(empty) == {}
    assert evidence.document_count(empty) == 0
    assert evidence.guardrail_counts(empty) == {"total": 0, "blocks": 0, "redactions": 0}
    assert evidence.guardrail_signature(empty) == ""
    assert evidence.cost_value(empty) is None
    summary = evidence.trace_summary(empty)
    assert summary["status"] == "success"
    assert summary["documents"] == 0
    assert evidence.diff_traces(empty, empty)
