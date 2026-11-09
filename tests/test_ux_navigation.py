"""Tests for UX1 (#130): role-aware information architecture in the console.

The navigation contract lives in ``ui/navigation.py`` and is deliberately free
of Streamlit/back-end imports, so these tests exercise real logic. Structural
assertions cover the wiring in ``ui/app.py`` and the onboarding step in the tour.
"""

import ast
from pathlib import Path

import pytest

from ui.navigation import (
    ALL_CAPABILITIES,
    CHECKLIST_STEPS,
    NAV_GROUPS,
    QUICK_ACTIONS,
    SCREEN_CAPABILITIES,
    can_access,
    checklist_status,
    effective_capabilities,
    grouped_screens,
    hidden_screens,
    landing_screen,
    quick_actions_for,
    role_label,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"

ANALYST = ["query", "batch", "evaluate", "experiment", "introspect"]
VIEWER = ["query", "introspect"]
SECURITY = ["introspect", "governance", "audit"]


def _screen_names():
    """Read the SCREENS dict keys from ui/app.py without importing Streamlit."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SCREENS":
                    return [key.value for key in node.value.keys]
    raise AssertionError("SCREENS dict literal not found")


def _tour_payloads():
    tree = ast.parse(TOUR_PATH.read_text(encoding="utf-8"), filename=str(TOUR_PATH))
    steps = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "TOUR_STEPS":
                steps = node.value
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and names[0] == "TOUR_STEPS":
                steps = node.value
    if steps is None:
        raise AssertionError("TOUR_STEPS literal not found")
    payloads = []
    for element in steps.elts:
        if isinstance(element, ast.Call):
            payloads.append(
                {
                    kw.arg: kw.value.value
                    for kw in element.keywords
                    if isinstance(kw.value, ast.Constant)
                }
            )
    return payloads


# -- information architecture ---------------------------------------------


def test_nav_groups_cover_every_screen_exactly_once():
    screens = _screen_names()
    flattened = [screen for group in NAV_GROUPS for screen in group.screens]
    assert sorted(flattened) == sorted(screens)
    assert len(flattened) == len(set(flattened))


def test_every_screen_has_a_capability_mapping():
    screens = _screen_names()
    assert set(SCREEN_CAPABILITIES) == set(screens)
    assert SCREEN_CAPABILITIES["Overview / Health"] is None
    assert SCREEN_CAPABILITIES["Approvals"] == "approve"
    for required in SCREEN_CAPABILITIES.values():
        if required is not None:
            assert required in ALL_CAPABILITIES


def test_effective_capabilities_disabled_grants_everything():
    assert effective_capabilities(False, ["query"]) == list(ALL_CAPABILITIES)
    assert sorted(effective_capabilities(True, ["query", "audit"])) == ["audit", "query"]


def test_can_access_honours_required_capabilities():
    assert can_access("Overview / Health", [])
    assert can_access("Query Studio", VIEWER)
    assert not can_access("Audit", VIEWER)
    assert can_access("Audit", SECURITY)


# -- role-based landing ----------------------------------------------------


@pytest.mark.parametrize(
    "role,capabilities,expected",
    [
        ("admin", list(ALL_CAPABILITIES), "Overview / Health"),
        ("analyst", ANALYST, "Evaluation"),
        ("security-reviewer", SECURITY, "Guardrails"),
        ("platform-ops", ["query", "governance", "introspect"], "Governance & Cost"),
        ("viewer", VIEWER, "Query Studio"),
        ("auditor", ["audit", "introspect"], "Audit"),
    ],
)
def test_landing_is_role_aware(role, capabilities, expected):
    assert landing_screen(role, capabilities, _screen_names()) == expected


def test_landing_skips_screens_the_role_cannot_open():
    # Analyst label, but no evaluate capability -> fall back to Overview.
    assert landing_screen("analyst", ["introspect"], _screen_names()) == "Overview / Health"


# -- capability filtering --------------------------------------------------


def test_grouped_screens_filters_viewer_role():
    groups = grouped_screens(_screen_names(), VIEWER)
    labels = [group.label for group in groups]
    assert labels == ["Start here", "Governance & security", "Reference"]
    shown = [screen for group in groups for screen in group.screens]
    assert "Query Studio" in shown
    assert "Guardrails" in shown
    assert "Audit" not in shown
    assert "Evaluation" not in shown
    assert "Admin" not in shown


def test_show_all_returns_every_screen_and_group():
    groups = grouped_screens(_screen_names(), VIEWER, show_all=True)
    shown = [screen for group in groups for screen in group.screens]
    assert sorted(shown) == sorted(_screen_names())
    assert [group.label for group in groups] == [group.label for group in NAV_GROUPS]


def test_hidden_screens_reports_role_restrictions():
    hidden = hidden_screens(_screen_names(), VIEWER)
    assert "Audit" in hidden and "Evaluation" in hidden
    assert hidden_screens(_screen_names(), VIEWER, show_all=True) == []


# -- quick actions / checklist --------------------------------------------


def test_quick_actions_are_capability_filtered():
    assert [action.label for action in quick_actions_for(VIEWER)] == ["Run a query"]
    assert len(quick_actions_for(ALL_CAPABILITIES)) == len(QUICK_ACTIONS)
    assert quick_actions_for([]) == []


def test_checklist_status_tracks_progress():
    statuses = checklist_status({})
    assert len(statuses) == len(CHECKLIST_STEPS)
    assert all(not done for _, done in statuses)

    all_done = checklist_status({step.key: True for step in CHECKLIST_STEPS})
    assert all(done for _, done in all_done)
    assert [step.key for step, _ in all_done] == [step.key for step in CHECKLIST_STEPS]


def test_checklist_steps_target_real_screens():
    screens = set(_screen_names())
    for step in CHECKLIST_STEPS:
        assert step.screen is None or step.screen in screens


def test_role_label_is_readable():
    assert role_label("platform-ops") == "Platform Ops"
    assert role_label("security_reviewer") == "Security Reviewer"
    assert role_label("") == "Unknown"


# -- structural wiring -----------------------------------------------------


def test_app_wires_role_navigation_and_checklist():
    text = APP_PATH.read_text(encoding="utf-8")
    for needle in (
        "from ui.navigation import",
        "_access_context(api)",
        "landing_screen(",
        "grouped_screens(",
        "quick_actions_for(",
        "checklist_status(",
        "_render_get_started(",
        "Get started",
        "st.session_state.active_screen",
    ):
        assert needle in text, f"ui/app.py is missing {needle!r}"


def test_app_navigation_uses_access_api_and_role_controls():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "api.access()" in text
    assert "Show all screens" in text
    assert "hidden by role" in text
    assert "nav_initialized" in text
    assert "active = st.session_state.get(\"active_screen\"" in text


def test_tour_has_a_get_started_step_and_sequential_numbers():
    payloads = _tour_payloads()
    assert any("Get started" in payload["title"] for payload in payloads)
    assert len(payloads) == 15
    for index, payload in enumerate(payloads, start=1):
        assert payload["title"].startswith(f"{index}."), payload["title"]
