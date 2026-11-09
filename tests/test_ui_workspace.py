"""Tests for UX8 (#151): persistent, shareable console workspace.

The workspace contract lives in ``ui/workspace.py`` and is deliberately free of
Streamlit/backend imports, so most tests exercise real normalization, bounds,
redaction, URL and export/import logic. Structural tests cover the wiring in
``ui/app.py`` and the tour without importing Streamlit.
"""

import ast
import random
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ui.navigation import ALL_CAPABILITIES
from ui.workspace import (
    DEFAULT_QUERY,
    DEFAULT_SCREEN,
    MAX_EXPORT_BYTES,
    MAX_RECENT_RUNS,
    MAX_SAVED_RUNS,
    MAX_SAVED_VIEWS_PER_KIND,
    MAX_URL_CHARS,
    WorkspaceError,
    add_recent_run,
    add_saved_run,
    add_saved_view,
    apply_saved_view,
    apply_workspace,
    build_share_url,
    empty_workspace,
    export_workspace,
    import_workspace,
    is_run_saved,
    merge_query_params,
    normalize_workspace,
    remove_saved_run,
    remove_saved_view,
    reset_workspace_state,
    saved_view_names,
    saved_views_for,
    scope_safe_workspace,
    workspace_from_query_params,
    workspace_from_session,
    workspace_scope_matches,
    workspace_signature,
    workspace_to_query_params,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"
REQUIREMENTS_UI = REPO_BASE / "requirements-ui.txt"
PYPROJECT = REPO_BASE / "pyproject.toml"

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
    "role": "analyst",
    "capabilities": list(ALL_CAPABILITIES),
    "tenant": {"id": "tenant-a", "workspace": "workspace-a"},
}


def _workspace(**overrides):
    workspace = empty_workspace()
    workspace.update(overrides)
    return normalize_workspace(workspace)


def _noise(length):
    rng = random.Random(151)
    return "".join(rng.choice("0123456789abcdef") for _ in range(length))


def _run(request_id, query="q", **overrides):
    run = {
        "request_id": request_id,
        "query": query,
        "top_k": 3,
        "timestamp": "2026-11-08T10:00:00+00:00",
        "outcome": "success",
    }
    run.update(overrides)
    return run


def _tour_titles():
    tree = ast.parse(TOUR_PATH.read_text(encoding="utf-8"), filename=str(TOUR_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = node.value if node.target.id == "TOUR_STEPS" else None
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value if names and names[0] == "TOUR_STEPS" else None
        else:
            value = None
        if value is not None and isinstance(value, ast.List):
            return [
                keyword.value.value
                for element in value.elts
                if isinstance(element, ast.Call)
                for keyword in element.keywords
                if keyword.arg == "title" and isinstance(keyword.value, ast.Constant)
            ]
    raise AssertionError("TOUR_STEPS list not found")


def test_empty_workspace_is_versioned_and_bounded():
    workspace = empty_workspace()
    assert workspace["version"] == 1
    assert workspace["screen"] == DEFAULT_SCREEN
    assert workspace["query_studio"]["query"] == DEFAULT_QUERY
    assert workspace["recent_runs"] == []
    assert workspace["saved_runs"] == []
    assert set(workspace["saved_views"]) == {
        "query",
        "compare",
        "evaluation",
        "governance",
        "audit",
        "approvals",
        "traces",
    }


def test_normalize_drops_unknown_and_secret_keys():
    normalized = normalize_workspace(
        {
            "version": 1,
            "api_key": "sk-should-not-survive",
            "unknown": {"anything": True},
            "query_studio": {
                "query": "api_key=sk-should-not-survive",
                "unknown": "drop",
            },
            "evaluation": {"token": "drop", "dataset_json": '{"secret": "sk-hidden"}'},
        }
    )
    assert "api_key" not in normalized
    assert "unknown" not in normalized
    assert "unknown" not in normalized["query_studio"]
    assert "token" not in normalized["evaluation"]
    assert "sk-should-not-survive" not in normalized["query_studio"]["query"]
    assert "sk-hidden" not in normalized["evaluation"]["dataset_json"]


def test_workspace_round_trips_through_url_blob():
    workspace = _workspace(
        screen="Evaluation",
        query_studio={
            "query": "How does RAG work?",
            "top_k": 7,
            "include_trace": False,
            "batch": True,
        },
        governance={
            "time_range": "Last 24 hours",
            "tenant": "tenant-a",
            "app": "support",
            "user": "alice",
        },
        evaluation={
            "query": "eval q",
            "response": "eval answer",
            "ground_truth": "reference",
            "evaluator": "semantic",
            "dataset_source": "Paste JSON",
            "dataset_json": '[{"query": "x"}]',
            "dataset_evaluator": "llm_judge",
            "dataset_top_k": 4,
        },
    )
    restored = workspace_from_query_params(workspace_to_query_params(workspace))
    assert restored["screen"] == "Evaluation"
    assert restored["query_studio"]["query"] == "How does RAG work?"
    assert restored["query_studio"]["top_k"] == 7
    assert restored["query_studio"]["include_trace"] is False
    assert restored["query_studio"]["batch"] is True
    assert restored["governance"]["time_range"] == "Last 24 hours"
    assert restored["governance"]["app"] == "support"
    assert restored["evaluation"]["response"] == "eval answer"
    assert restored["evaluation"]["ground_truth"] == "reference"
    assert restored["evaluation"]["dataset_json"] == '[{"query": "x"}]'
    assert restored["evaluation"]["dataset_top_k"] == 4


def test_direct_query_params_override_blob():
    workspace = _workspace(
        screen="Query Studio",
        query_studio={"query": "blob query", "top_k": 7},
    )
    params = workspace_to_query_params(workspace)
    params["q"] = "direct query"
    params["top_k"] = "2"
    restored = workspace_from_query_params(params)
    assert restored["query_studio"]["query"] == "direct query"
    assert restored["query_studio"]["top_k"] == 2


def test_corrupt_blob_falls_back_to_direct_params():
    restored = workspace_from_query_params(
        {"ws": "not-base64!!!", "screen": "Query Studio", "q": "fallback"}
    )
    assert restored["screen"] == "Query Studio"
    assert restored["query_studio"]["query"] == "fallback"


def test_query_and_compare_fields_persist():
    workspace = _workspace(
        screen="Compare (what-if)",
        compare={"metric": "l2", "retriever": "simple", "query": "compare me"},
    )
    restored = workspace_from_query_params(workspace_to_query_params(workspace))
    assert restored["compare"] == {
        "metric": "l2",
        "retriever": "simple",
        "query": "compare me",
    }


def test_governance_audit_and_trace_fields_persist():
    workspace = _workspace(
        screen="Traces",
        governance={
            "time_range": "Last 7 days",
            "tenant": "tenant-a",
            "app": "support",
            "user": "bob",
        },
        audit={"limit": 250, "event_type": "governance"},
        traces={"request_id": "req-trace-1"},
        activity={
            "last_request_id": "req-trace-1",
            "last_trace_request_id": "req-trace-1",
        },
    )
    restored = workspace_from_query_params(workspace_to_query_params(workspace))
    assert restored["governance"]["tenant"] == "tenant-a"
    assert restored["governance"]["app"] == "support"
    assert restored["audit"] == {"limit": 250, "event_type": "governance"}
    assert restored["traces"]["request_id"] == "req-trace-1"


def test_evaluation_fields_persist_and_clamp():
    workspace = normalize_workspace(
        {
            "evaluation": {
                "dataset_top_k": 99,
                "dataset_source": "not-a-source",
                "dataset_json": "x" * 50_000,
            }
        }
    )
    assert workspace["evaluation"]["dataset_top_k"] == 10
    assert workspace["evaluation"]["dataset_source"] == "Built-in benchmark"
    assert len(workspace["evaluation"]["dataset_json"]) == 20_000


def test_saved_views_add_replace_delete_and_cap():
    workspace = empty_workspace()
    for index in range(MAX_SAVED_VIEWS_PER_KIND + 2):
        workspace = add_saved_view(workspace, "governance", f"view-{index}")
    assert saved_view_names(workspace, "governance") == [
        "view-6",
        "view-5",
        "view-4",
        "view-3",
        "view-2",
    ]

    workspace = add_saved_view(workspace, "governance", "view-4")
    assert saved_view_names(workspace, "governance")[0] == "view-4"
    assert len(saved_view_names(workspace, "governance")) == MAX_SAVED_VIEWS_PER_KIND

    workspace = remove_saved_view(workspace, "governance", "VIEW-4")
    assert "view-4" not in saved_view_names(workspace, "governance")


def test_saved_view_captures_only_its_section():
    workspace = _workspace(
        screen="Governance & Cost",
        query_studio={"query": "query value", "top_k": 6},
        governance={"tenant": "tenant-a", "app": "app-a"},
    )
    workspace = add_saved_view(workspace, "query", "my query view")
    entries = saved_views_for(workspace, "query")
    assert len(entries) == 1
    assert entries[0]["screen"] == "Query Studio"
    assert entries[0]["section"] == "query_studio"
    assert set(entries[0]["values"]) == {
        "query",
        "top_k",
        "include_trace",
        "batch",
    }
    assert "governance" not in entries[0]["values"]


def test_apply_saved_view_preserves_other_state():
    workspace = _workspace(
        screen="Query Studio",
        query_studio={"query": "first", "top_k": 5},
        governance={"tenant": "keep-me", "app": "keep-app"},
    )
    workspace = add_saved_view(workspace, "query", "saved query")
    workspace = normalize_workspace(
        {
            **workspace,
            "query_studio": {"query": "changed", "top_k": 1},
        }
    )
    applied = apply_saved_view(workspace, "query", "saved query")
    assert applied["screen"] == "Query Studio"
    assert applied["query_studio"]["query"] == "first"
    assert applied["query_studio"]["top_k"] == 5
    assert applied["governance"]["tenant"] == "keep-me"


def test_recent_runs_are_summaries_without_payloads():
    workspace = add_recent_run(
        empty_workspace(),
        {
            **_run("req-1", "query one"),
            "response": "secret answer",
            "result": {"api_key": "sk-leak"},
        },
    )
    assert workspace["recent_runs"][0]["request_id"] == "req-1"
    assert "result" not in workspace["recent_runs"][0]
    assert "response" not in workspace["recent_runs"][0]


def test_recent_and_saved_runs_dedupe_and_bound():
    workspace = empty_workspace()
    for index in range(MAX_RECENT_RUNS + 5):
        workspace = add_recent_run(workspace, _run(f"recent-{index}", f"q-{index}"))
    assert len(workspace["recent_runs"]) == MAX_RECENT_RUNS
    assert workspace["recent_runs"][0]["request_id"] == f"recent-{MAX_RECENT_RUNS + 4}"

    workspace = add_recent_run(workspace, _run("recent-10", "updated"))
    assert workspace["recent_runs"][0]["query"] == "updated"
    assert sum(1 for run in workspace["recent_runs"] if run["request_id"] == "recent-10") == 1

    for index in range(MAX_SAVED_RUNS + 5):
        workspace = add_saved_run(workspace, _run(f"saved-{index}", f"q-{index}"))
    assert len(workspace["saved_runs"]) == MAX_SAVED_RUNS
    assert is_run_saved(workspace, "saved-5")
    workspace = remove_saved_run(workspace, "saved-5")
    assert not is_run_saved(workspace, "saved-5")


def test_export_import_round_trip():
    workspace = _workspace(
        screen="Traces",
        query_studio={"query": "exported", "top_k": 4},
        traces={"request_id": "req-42"},
        saved_runs=[_run("req-42", "exported")],
    )
    imported = import_workspace(export_workspace(workspace))
    assert workspace_signature(imported) == workspace_signature(workspace)


def test_import_rejects_bad_json_version_and_oversize():
    with pytest.raises(WorkspaceError):
        import_workspace("{")
    with pytest.raises(WorkspaceError):
        import_workspace('{"version": 99}')
    with pytest.raises(WorkspaceError):
        import_workspace("[]")
    with pytest.raises(WorkspaceError):
        import_workspace("x" * (MAX_EXPORT_BYTES + 1))


def test_export_rejects_oversize():
    workspace = empty_workspace()
    huge = {
        "query": "q" * 2_000,
        "response": "r" * 8_000,
        "ground_truth": "g" * 8_000,
        "dataset_json": "d" * 20_000,
    }
    workspace["evaluation"] = normalize_workspace({"evaluation": huge})["evaluation"]
    for index in range(MAX_SAVED_VIEWS_PER_KIND):
        workspace = add_saved_view(workspace, "evaluation", f"huge-{index}")
    for index in range(MAX_SAVED_RUNS):
        workspace = add_saved_run(workspace, _run(f"saved-{index}", "q" * 2_000))
    with pytest.raises(WorkspaceError):
        export_workspace(workspace)


def test_secrets_are_redacted_from_url_and_export():
    workspace = normalize_workspace(
        {
            "screen": "Query Studio",
            "query_studio": {
                "query": "use ${OPENAI_API_KEY} and sk-abcdefghijkl",
            },
            "evaluation": {
                "response": "Authorization: Bearer abcdefghijklmnop",
                "dataset_json": '{"token": "secretvalue"}',
            },
        }
    )
    exported = export_workspace(workspace)
    params = workspace_to_query_params(workspace)
    decoded = workspace_from_query_params(params)
    for text in (
        exported,
        params["q"],
        decoded["query_studio"]["query"],
        decoded["evaluation"]["response"],
        decoded["evaluation"]["dataset_json"],
    ):
        assert "OPENAI_API_KEY" not in text
        assert "sk-abcdefghijkl" not in text
        assert "abcdefghijklmnop" not in text
        assert "secretvalue" not in text


def test_scope_mismatch_drops_tenant_specific_state():
    workspace = _workspace(
        screen="Query Studio",
        scope={"tenant": "tenant-b", "workspace": "workspace-b"},
        query_studio={"query": "tenant-b query"},
        saved_runs=[_run("req-b", "tenant-b query")],
    )
    assert not workspace_scope_matches(workspace, ACCESS)
    safe, warning = scope_safe_workspace(workspace, ACCESS, SCREENS)
    assert warning
    assert safe["screen"] == "Query Studio"
    assert safe["query_studio"]["query"] == DEFAULT_QUERY
    assert safe["saved_runs"] == []


def test_inaccessible_screen_falls_back_to_landing():
    state = {}
    access = {
        "ok": True,
        "enabled": True,
        "role": "analyst",
        "capabilities": ["query"],
        "tenant": {"id": "", "workspace": ""},
    }
    screen = apply_workspace(_workspace(screen="Audit"), state, access, SCREENS)
    assert screen == "Overview / Health"
    assert state["active_screen"] == "Overview / Health"


def test_apply_workspace_sets_state_and_trace_autoload():
    state = {}
    workspace = _workspace(
        screen="Traces",
        scope={"tenant": "tenant-a", "workspace": "workspace-a"},
        query_studio={"query": "state query", "top_k": 6},
        governance={"tenant": "tenant-a", "app": "support", "time_range": "Last 24 hours"},
        audit={"limit": 100, "event_type": "governance"},
        traces={"request_id": "req-trace-9"},
        activity={
            "last_request_id": "req-trace-9",
            "last_query": "state query",
            "last_trace_request_id": "req-trace-9",
            "last_governance_seen": True,
        },
        recent_runs=[_run("req-trace-9", "state query")],
        saved_runs=[_run("req-trace-9", "state query")],
    )
    screen = apply_workspace(workspace, state, ACCESS, SCREENS)
    assert screen == "Traces"
    assert state["active_screen"] == "Traces"
    assert state["qs_query"] == "state query"
    assert state["qs_top_k"] == 6
    assert state["gov_tenant"] == "tenant-a"
    assert state["gov_app"] == "support"
    assert state["audit_limit"] == 100
    assert state["trace_request_id"] == "req-trace-9"
    assert state["trace_autoload"] is True
    assert state["query_history"][0]["request_id"] == "req-trace-9"
    assert state["workspace_saved_runs"][0]["request_id"] == "req-trace-9"


def test_apply_workspace_restores_empty_dataset_instead_of_keeping_stale_text():
    state = {"evaluation_dataset_json": "stale dataset"}
    workspace = _workspace(
        screen="Evaluation",
        evaluation={"dataset_json": "", "dataset_source": "Paste JSON"},
    )
    apply_workspace(workspace, state, ACCESS, SCREENS)
    assert state["evaluation_dataset_json"] == ""
    assert state["evaluation_dataset_source"] == "Paste JSON"


def test_apply_workspace_restores_governance_filters():
    state = {}
    workspace = _workspace(
        screen="Governance & Cost",
        governance={
            "time_range": "Last 7 days",
            "tenant": "tenant-a",
            "app": "support",
            "user": "alice",
        },
    )
    apply_workspace(workspace, state, ACCESS, SCREENS)
    assert state["gov_time_range"] == "Last 7 days"
    assert state["gov_tenant"] == "tenant-a"
    assert state["gov_app"] == "support"
    assert state["gov_user"] == "alice"


def test_reset_workspace_state_preserves_api_settings():
    state = {
        "api_base_url": "http://localhost:9000",
        "api_key": "secret-key",
        "tour_state": "idle",
        "qs_query": "changed",
        "query_history": [_run("req-1")],
        "workspace_saved_views": {"query": [{"name": "x"}]},
    }
    reset_workspace_state(state)
    assert state["api_base_url"] == "http://localhost:9000"
    assert state["api_key"] == "secret-key"
    assert state["tour_state"] == "idle"
    assert state["active_screen"] == DEFAULT_SCREEN
    assert state["qs_query"] == DEFAULT_QUERY
    assert state["query_history"] == []
    assert state["workspace_saved_views"]["query"] == []


def test_build_share_url_drops_bulk_to_fit_budget():
    workspace = _workspace(
        screen="Evaluation",
        evaluation={"dataset_json": _noise(20_000), "response": _noise(8_000)},
    )
    for index in range(MAX_SAVED_VIEWS_PER_KIND):
        workspace = add_saved_view(workspace, "evaluation", f"view-{index}")
    url = build_share_url("http://localhost:8501", workspace)
    assert len(url) <= MAX_URL_CHARS
    params = parse_qs(urlsplit(url).query)
    restored = workspace_from_query_params(
        {key: values[0] for key, values in params.items()}
    )
    assert restored["evaluation"]["dataset_json"] == ""
    assert restored["evaluation"]["response"] == "RAG grounds an LLM on retrieved documents."
    assert restored["saved_views"]["evaluation"] == []


def test_merge_query_params_preserves_unknown_params():
    merged = merge_query_params(
        {"embed": "true", "screen": "old", "q": "old"},
        {"screen": "new", "q": "new"},
    )
    assert merged["embed"] == "true"
    assert merged["screen"] == "new"
    assert merged["q"] == "new"


def test_direct_request_id_serializes_only_for_the_traces_screen():
    query_workspace = workspace_from_query_params(
        {"screen": "Query Studio", "request_id": "req-direct"}
    )
    assert query_workspace["traces"]["request_id"] == "req-direct"
    assert "request_id" not in workspace_to_query_params(query_workspace)

    trace_workspace = workspace_from_query_params(
        {"screen": "Traces", "request_id": "req-direct"}
    )
    trace_params = workspace_to_query_params(trace_workspace)
    assert trace_params["request_id"] == "req-direct"
    restored = workspace_from_query_params(trace_params)
    assert workspace_signature(restored) == workspace_signature(trace_workspace)


def test_workspace_signature_changes_only_with_normalized_state():
    first = _workspace(screen="Query Studio", query_studio={"query": "same"})
    second = dict(first)
    second["ignored"] = "unknown"
    third = _workspace(screen="Query Studio", query_studio={"query": "different"})
    assert workspace_signature(first) == workspace_signature(second)
    assert workspace_signature(first) != workspace_signature(third)


def test_workspace_from_session_reads_widget_state():
    workspace = workspace_from_session(
        {
            "active_screen": "Governance & Cost",
            "qs_query": "session query",
            "qs_top_k": 8,
            "qs_include_trace": False,
            "qs_batch": True,
            "eval_query": "eval query",
            "gov_time_range": "Last 7 days",
            "gov_tenant": "tenant-a",
            "audit_limit": 200,
            "audit_event_type": "pii",
            "trace_request_id": "req-9",
            "last_request_id": "req-9",
            "query_history": [_run("req-9", "session query")],
        },
        scope={"tenant": "tenant-a", "workspace": "workspace-a"},
    )
    assert workspace["screen"] == "Governance & Cost"
    assert workspace["query_studio"]["query"] == "session query"
    assert workspace["query_studio"]["top_k"] == 8
    assert workspace["query_studio"]["batch"] is True
    assert workspace["evaluation"]["query"] == "eval query"
    assert workspace["governance"]["time_range"] == "Last 7 days"
    assert workspace["audit"]["limit"] == 200
    assert workspace["traces"]["request_id"] == "req-9"
    assert workspace["scope"]["tenant"] == "tenant-a"


def test_workspace_module_is_streamlit_and_backend_free():
    tree = ast.parse(
        (REPO_BASE / "ui" / "workspace.py").read_text(encoding="utf-8"),
        filename="ui/workspace.py",
    )
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    offenders = [name for name in modules if name.split(".")[0] in ("app", "core", "streamlit")]
    assert not offenders


def test_streamlit_minimum_is_1_65():
    requirements = REQUIREMENTS_UI.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert "streamlit>=1.65" in requirements
    assert "streamlit>=1.65" in pyproject


def test_app_wires_workspace_controls_and_url_sync():
    text = APP_PATH.read_text(encoding="utf-8")
    for needle in (
        "from ui.workspace import",
        "workspace_from_query_params(",
        "workspace_to_query_params(",
        "workspace_signature(",
        "build_share_url(",
        "st.query_params",
        "Share this view",
        "Export workspace",
        "Import workspace",
        "Reset workspace",
        "Saved views",
        "trace_autoload",
    ):
        assert needle in text, f"missing workspace wiring: {needle!r}"


def test_tour_has_workspace_step():
    titles = _tour_titles()
    assert any("workspace" in title.lower() for title in titles)
