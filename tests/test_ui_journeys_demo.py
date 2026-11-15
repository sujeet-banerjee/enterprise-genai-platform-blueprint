"""Role-based guided journeys and safe local demo mode (issue #157).

The journey/demo contract lives in ``ui/journeys.py`` and ``ui/demo.py`` and is
deliberately Streamlit- and backend-free, so it is unit-tested here. The
structural tests parse ``ui/app.py`` and ``ui/tour.py`` with :mod:`ast` to prove
the console actually wires the journeys, the checklist extension, the demo
banner and the reset path.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Dict, List

import pytest

from ui import journeys
from ui.journeys import (
    DEMO_EPOCH,
    DEMO_QUERY,
    DEMO_REQUEST_ID,
    DEMO_RESULT,
    DEMO_ROLE,
    DEMO_SEED_KEYS,
    DEMO_TENANT,
    DEMO_WORKSPACE,
    DOC_BASE_URL,
    ROLE_JOURNEYS,
    demo_reset_state,
    demo_seed_state,
    doc_url,
    journey_by_key,
    journey_for_role,
    journey_key_for_label,
    journey_labels,
    journey_markdown,
    journey_progress,
    mark_screen_visited,
)
from ui.navigation import (
    ALL_CAPABILITIES,
    CHECKLIST_STEPS,
    SCREEN_CAPABILITIES,
    checklist_status,
    effective_capabilities,
)

REPO_BASE = Path(__file__).resolve().parents[1]
UI_DIR = REPO_BASE / "ui"
APP_PATH = UI_DIR / "app.py"
TOUR_PATH = UI_DIR / "tour.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _screens() -> Dict[str, str]:
    """Return the ``SCREENS`` mapping (key -> screen function name) from app.py."""
    for node in ast.walk(_tree(APP_PATH)):
        if isinstance(node, ast.Assign):
            names = [getattr(target, "id", "") for target in node.targets]
        elif isinstance(node, ast.AnnAssign):
            names = [getattr(node.target, "id", "")]
        else:
            names = []
        if names and names[0] == "SCREENS" and isinstance(node.value, ast.Dict):
            return {
                str(key.value): getattr(value, "id", "")
                for key, value in zip(node.value.keys, node.value.values)
            }
    raise AssertionError("SCREENS mapping not found in ui/app.py")


def _tour_payloads() -> List[dict]:
    for node in ast.walk(_tree(TOUR_PATH)):
        if isinstance(node, ast.Assign):
            names = [getattr(target, "id", "") for target in node.targets]
        elif isinstance(node, ast.AnnAssign):
            names = [getattr(node.target, "id", "")]
        else:
            names = []
        if names and names[0] == "TOUR_STEPS" and isinstance(node.value, ast.List):
            payloads = []
            for element in node.value.elts:
                if not isinstance(element, ast.Call):
                    continue
                payloads.append(
                    {
                        keyword.arg: keyword.value.value
                        for keyword in element.keywords
                        if isinstance(keyword.value, ast.Constant)
                    }
                )
            return payloads
    raise AssertionError("TOUR_STEPS list literal not found in ui/tour.py")


# -- role journeys ---------------------------------------------------------


def test_role_journeys_cover_the_documented_personas():
    assert set(ROLE_JOURNEYS) == {"architect", "analyst", "security", "ops", "admin"}
    assert journey_labels() == [ROLE_JOURNEYS[key].label for key in ROLE_JOURNEYS]
    for journey in ROLE_JOURNEYS.values():
        assert journey.audience
        assert journey.description
        assert 4 <= len(journey.steps) <= 6, journey.key
        for step in journey.steps:
            assert step.title and step.goal and step.try_it and step.doc


@pytest.mark.parametrize(
    "role,expected",
    [
        ("architect", "architect"),
        ("Solution Architect", "architect"),
        ("analyst", "analyst"),
        ("ml-engineer", "analyst"),
        ("security-reviewer", "security"),
        ("compliance", "security"),
        ("sre", "ops"),
        ("platform-ops", "ops"),
        ("finops", "ops"),
        ("admin", "admin"),
        ("tenant-admin", "admin"),
        ("", "architect"),
        ("unknown-persona", "architect"),
    ],
)
def test_journey_for_role_maps_free_form_labels(role: str, expected: str):
    assert journey_for_role(role).key == expected


def test_journey_label_round_trip_and_unknown_key_fallback():
    for label in journey_labels():
        assert journey_by_key(journey_key_for_label(label)).label == label
    assert journey_key_for_label("not a journey") == DEMO_ROLE
    assert journey_by_key("nope").key == DEMO_ROLE


def test_every_journey_step_targets_a_real_screen_and_existing_doc():
    screens = set(_screens())
    for journey in ROLE_JOURNEYS.values():
        for step in journey.steps:
            assert step.screen in screens, (journey.key, step.screen)
            doc_path = step.doc.split("#", 1)[0]
            assert (REPO_BASE / doc_path).is_file(), (journey.key, doc_path)
            assert doc_url(step.doc).startswith(DOC_BASE_URL)
            assert doc_url(step.doc).endswith(step.doc)


def test_journey_progress_tracks_visited_screens_once():
    journey = ROLE_JOURNEYS["analyst"]
    # The analyst journey revisits Query Studio, so one visited screen can
    # complete more than one step.
    completed = {journey.steps[0].screen: True, journey.steps[1].screen: False}
    assert journey_progress("analyst", completed) == (2, len(journey.steps))

    visited = mark_screen_visited([], "Traces")
    visited = mark_screen_visited(visited, "Traces")
    visited = mark_screen_visited(visited, "Query Studio")
    assert visited == ["Traces", "Query Studio"]
    assert mark_screen_visited(visited, "") == visited

    for key in ROLE_JOURNEYS:
        steps = ROLE_JOURNEYS[key].steps
        full = {step.screen: True for step in steps}
        done, total = journey_progress(key, full)
        assert (done, total) == (len(steps), len(steps))


def test_journey_markdown_contains_goals_docs_and_no_secret_values():
    for key in ROLE_JOURNEYS:
        markdown = journey_markdown(key)
        assert ROLE_JOURNEYS[key].label in markdown
        for step in ROLE_JOURNEYS[key].steps:
            assert step.title in markdown
            assert step.doc in markdown
        assert "sk-" not in markdown
        assert "Bearer " not in markdown
        assert "api_key=" not in markdown


# -- checklist extension ---------------------------------------------------


def test_checklist_covers_guardrails_audit_and_admin():
    keys = {step.key for step in CHECKLIST_STEPS}
    assert {"backend", "query", "trace", "evaluate", "governance"} <= keys
    assert {"guardrails", "audit", "admin"} <= keys
    targets = {step.key: step.screen for step in CHECKLIST_STEPS}
    assert targets["guardrails"] == "Guardrails"
    assert targets["audit"] == "Audit"
    assert targets["admin"] == "Admin"


def test_checklist_filters_steps_by_capabilities():
    full = checklist_status({}, effective_capabilities(False, []))
    assert len(full) == len(CHECKLIST_STEPS)

    viewer_caps = ["query", "evaluate"]
    filtered = {step.key for step, _ in checklist_status({}, viewer_caps)}
    assert {"backend", "query", "evaluate"} <= filtered
    assert "guardrails" not in filtered
    assert "audit" not in filtered
    assert "admin" not in filtered
    assert "governance" not in filtered

    # Backward-compatible: no capabilities argument keeps every step.
    assert len(checklist_status({})) == len(CHECKLIST_STEPS)
    # Every capability used by the checklist maps to a real screen capability.
    for step in CHECKLIST_STEPS:
        if step.screen is not None:
            required = SCREEN_CAPABILITIES[step.screen]
            assert step.capability == required, step.key


def test_tour_covers_every_screen_and_the_new_journey_step():
    payloads = _tour_payloads()
    assert len(payloads) == 16
    for index, payload in enumerate(payloads, start=1):
        assert payload["title"].startswith(f"{index}.")
    assert any("Role journeys" in payload["title"] for payload in payloads)
    assert any("demo mode" in payload["body"].lower() for payload in payloads)
    covered = {payload["screen"] for payload in payloads}
    for screen in _screens():
        assert screen in covered, f"tour misses screen {screen!r}"


# -- demo seed / reset -----------------------------------------------------


def test_demo_seed_is_local_and_populates_every_screen():
    state = demo_seed_state("security")
    assert state["demo_mode"] is True
    assert state["demo_role"] == "security"
    assert state["journey_state"] == "running"
    assert state["journey_role"] == "security"
    assert state["last_request_id"] == DEMO_REQUEST_ID
    assert state["last_trace_request_id"] == DEMO_REQUEST_ID
    assert state["last_query"] == DEMO_QUERY
    assert len(state["query_history"]) == 1
    assert state["saved_datasets"]
    assert state["workspace_scope"] == {"tenant": DEMO_TENANT, "workspace": DEMO_WORKSPACE}
    for key in ("last_guardrail_at", "last_audit_at", "last_admin_at"):
        assert state[key]
    for key in DEMO_SEED_KEYS:
        assert key in state, f"seed state is missing {key!r}"


def test_demo_reset_clears_demo_data_and_leaves_a_clean_workspace():
    state = demo_seed_state("analyst")
    state["workspace_saved_views"] = {"query": {"name": "demo view"}}
    reset = demo_reset_state(state)

    assert reset["demo_mode"] is False
    assert reset["demo_role"] == ""
    assert reset["demo_started_at"] == ""
    assert reset["query_history"] == []
    assert reset["saved_datasets"] == []
    assert reset["workspace_saved_views"] == {}
    assert reset["workspace_saved_runs"] == []
    assert reset["journey_visited"] == []
    assert reset["workspace_scope"] == {"tenant": "", "workspace": ""}
    assert reset["active_screen"] == "Overview / Health"
    assert reset["checklist_hidden"] is False
    assert reset["last_request_id"] == ""

    dumped_data = json.dumps(
        {
            "workspace_scope": reset["workspace_scope"],
            "query_history": reset["query_history"],
            "saved_datasets": reset["saved_datasets"],
            "last_request_id": reset["last_request_id"],
            "last_trace_request_id": reset["last_trace_request_id"],
            "journey_visited": reset["journey_visited"],
        },
        default=str,
        sort_keys=True,
    )
    for marker in (DEMO_REQUEST_ID, DEMO_TENANT, DEMO_WORKSPACE):
        assert marker not in dumped_data, f"reset leaks demo marker {marker!r}"
    assert reset["last_query"] == ""
    assert reset["qs_last_entry"] is None
    assert reset["qs_last_baseline"] is None

    # Clearing twice is safe.
    assert demo_reset_state(reset)["demo_mode"] is False


def test_demo_fixture_shapes_match_documented_responses():
    access = journeys.demo_fixture("/v1/access")
    assert access["role"] == "architect"
    assert set(ALL_CAPABILITIES) <= set(access["capabilities"])
    assert access["tenant"]["workspace"] == DEMO_WORKSPACE

    models = journeys.demo_fixture("/v1/models")
    assert models["active"] in {model["name"] for model in models["models"]}
    assert models["active_config"]["context_window"] > 0

    assert journeys.demo_fixture("/v1/embedding-models")["active"]
    assert journeys.demo_fixture("/v1/retrievers")["providers"]
    assert journeys.demo_fixture("/v1/rerankers")["providers"]
    assert journeys.demo_fixture("/v1/evaluators")["providers"]

    query = journeys.demo_fixture("/v1/query", method="POST", payload={"query": DEMO_QUERY})
    assert query["request_id"] == DEMO_REQUEST_ID
    assert query["response"]
    assert query["retrieved_docs_with_scores"]
    assert query["observability"]["resilience"]["served_by"]

    governance = journeys.demo_fixture("/v1/governance/status")
    assert governance["window"]["requests"] >= 1

    metrics = journeys.demo_fixture("/v1/metrics")
    assert metrics["total_runs"] >= 1
    assert metrics["totals"]["requests"] >= 1
    assert isinstance(metrics["guardrails"]["by_decision"], dict)

    trace = journeys.demo_fixture(f"/v1/traces/{DEMO_REQUEST_ID}")
    assert trace["request_id"] == DEMO_REQUEST_ID
    assert trace["observability"]["otel"]["trace_id"]

    approvals = journeys.demo_fixture("/v1/approvals")
    assert approvals["count"] == len(approvals["requests"])
    assert isinstance(approvals["requests"][0]["created_at"], float)
    assert approvals["requests"][0]["created_at"] == DEMO_EPOCH

    tenants = journeys.demo_fixture("/v1/admin/tenants")
    assert tenants["current"]["id"] == DEMO_TENANT
    assert tenants["tenants"]

    guardrails = journeys.demo_fixture("/v1/guardrails")
    assert guardrails["profile"]
    assert guardrails["input"] and guardrails["output"]

    config = journeys.demo_fixture("/v1/config")
    assert config["demo"] is True

    ready = journeys.demo_fixture("/ready")
    assert ready["status"] == "ready"

    assert DEMO_RESULT["latency"]["total_ms"] > 0


def test_demo_api_never_issues_http_requests(monkeypatch):
    requests = pytest.importorskip("requests")

    def _fail(*_args, **_kwargs):
        raise AssertionError("demo mode must not perform HTTP requests")

    monkeypatch.setattr(requests, "request", _fail)
    monkeypatch.setattr(requests.Session, "request", _fail)

    from ui.demo import DemoApi

    api = DemoApi("security")
    results = [
        api.health(),
        api.ready(),
        api.models(),
        api.embedding_models(),
        api.retrievers(),
        api.rerankers(),
        api.evaluators(),
        api.guardrails(),
        api.access(),
        api.effective_config(),
        api.query(DEMO_QUERY),
        api.batch_query([DEMO_QUERY, "second question"]),
        api.evaluate(DEMO_QUERY, "demo answer"),
        api.launch_experiment(kind="compare_chunking_strategies"),
        api.get_experiment("demo-experiment"),
        api.rebuild({"top_k": 3}),
        api.governance_status(),
        api.trace(DEMO_REQUEST_ID),
        api.metrics(),
        api.audit(limit=5),
        api.approvals(),
        api.approval(DEMO_REQUEST_ID),
        api.decide_approval(DEMO_REQUEST_ID, "approved"),
        api.admin_list_tenants(),
        api.admin_update_tenant(DEMO_TENANT, {"budget_cap_usd": 2.0}),
        api.admin_list_users(),
        api.prometheus_metrics(),
    ]
    assert all(result.ok for result in results)
    assert results[8].data["role"] == "security"


# -- console wiring --------------------------------------------------------


def test_app_wires_journeys_demo_banner_and_reset():
    text = APP_PATH.read_text(encoding="utf-8")
    for needle in (
        "from ui.journeys import",
        "DEMO_WARNING",
        "demo_seed_state(",
        "demo_reset_state(",
        "journey_for_role(",
        "journey_progress(",
        "journey_markdown(",
        "doc_url(",
        "mark_screen_visited(",
        "def _render_role_journey(",
        "def _render_demo_sidebar(",
        "def render_role_journey(",
        "_render_role_journey(access)",
        "_render_demo_sidebar(access)",
        "_mark_journey_visit(active)",
        "st.warning(DEMO_WARNING)",
        "Exit demo and reset",
        "Start demo",
        "Start / restart journey",
        "Skip journey",
    ):
        assert needle in text, f"ui/app.py is missing {needle!r}"


def test_app_uses_demo_api_only_when_demo_mode_is_active():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "from ui.demo import DemoApi" in text
    start = text.index("def client(")
    end = text.index("\ndef ", start + 1)
    body = text[start:end]
    assert "demo_mode" in body
    assert "DemoApi(" in body
    assert "return ApiClient(" in body
    assert "api_base_url()" in body


def test_app_marks_checklist_flags_from_real_screens():
    text = APP_PATH.read_text(encoding="utf-8")
    assert text.count("st.session_state.last_guardrail_at =") == 1
    assert text.count("st.session_state.last_audit_at =") == 1
    assert text.count("st.session_state.last_admin_at =") == 1
    assert '"guardrails": bool(st.session_state.get("last_guardrail_at"))' in text
    assert '"audit": bool(st.session_state.get("last_audit_at"))' in text
    assert '"admin": bool(st.session_state.get("last_admin_at"))' in text
    assert "checklist_status(done, capabilities)" in text
