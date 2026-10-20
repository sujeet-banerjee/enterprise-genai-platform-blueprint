"""Tests for the first-time-user guided tour and the enhanced Evaluation screen.

Streamlit is a UI-only dependency and is not installed in CI, so these tests stay
structural: they parse ``ui/tour.py`` and ``ui/app.py`` with :mod:`ast` and assert
the tour contract (a step per screen, Back/Next/Skip controls, Help expander) and
the new Evaluation controls (evaluator dropdown, optional ground truth) exist
without importing Streamlit.
"""

import ast
from pathlib import Path
from typing import List

REPO_BASE = Path(__file__).resolve().parents[1]
UI_DIR = REPO_BASE / "ui"
TOUR_PATH = UI_DIR / "tour.py"
APP_PATH = UI_DIR / "app.py"

SCREENS = [
    "Overview / Health",
    "Query Studio",
    "Compare (what-if)",
    "Evaluation",
    "Governance & Cost",
    "Traces",
    "Settings (read-only)",
]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _tour_steps_list() -> ast.List:
    """Return the list literal assigned to TOUR_STEPS (handles AnnAssign)."""
    tree = _tree(TOUR_PATH)
    for node in ast.walk(tree):
        target_name = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            target_name = targets[0] if targets else None
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
        if target_name == "TOUR_STEPS" and isinstance(node.value, ast.List):
            return node.value
    raise AssertionError("TOUR_STEPS list literal not found")


def _tour_titles() -> List[str]:
    """Extract the TourStep ``title`` strings from the TOUR_STEPS list literal."""
    titles: List[str] = []
    for element in _tour_steps_list().elts:
        if isinstance(element, ast.Call):
            for kw in element.keywords:
                if kw.arg == "title" and isinstance(kw.value, ast.Constant):
                    titles.append(kw.value.value)
    return titles


def _tour_payloads() -> List[dict]:
    payloads: List[dict] = []
    for element in _tour_steps_list().elts:
        if isinstance(element, ast.Call):
            entry = {
                kw.arg: kw.value.value
                for kw in element.keywords
                if isinstance(kw.value, ast.Constant)
            }
            payloads.append(entry)
    return payloads


def test_tour_module_exists():
    assert TOUR_PATH.exists()
    assert APP_PATH.exists()


def test_tour_has_a_step_per_screen():
    screens = {payload["screen"] for payload in _tour_payloads()}
    for screen in SCREENS:
        assert screen in screens, f"tour is missing a step for screen {screen!r}"


def test_tour_has_sidebar_and_evaluation_steps():
    screens = {payload["screen"] for payload in _tour_payloads()}
    assert "Sidebar" in screens
    assert "Evaluation" in screens


def test_tour_steps_are_numbered_and_nonempty():
    titles = _tour_titles()
    assert len(titles) >= len(SCREENS)
    for index, title in enumerate(titles, start=1):
        assert title.startswith(f"{index}."), f"step {index} title not numbered: {title!r}"
    for payload in _tour_payloads():
        assert payload.get("body")
        assert payload.get("try_it")


def test_tour_exposes_controls_and_help():
    names = {
        node.name
        for node in ast.walk(_tree(TOUR_PATH))
        if isinstance(node, ast.FunctionDef)
    }
    assert {"render_tour", "render_help_expander", "start_tour"} <= names


def test_tour_controls_back_next_skip_present():
    text = TOUR_PATH.read_text(encoding="utf-8")
    for label in ("Back", "Next", "Finish", "Skip tour", "Take the tour", "Restart tour"):
        assert label in text, f"missing tour control: {label!r}"


def test_tour_does_not_import_backend():
    modules: List[str] = []
    for node in ast.walk(_tree(TOUR_PATH)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    offenders = [m for m in modules if m.split(".")[0] in ("app", "core")]
    assert not offenders, f"tour imports backend modules {offenders}"


def test_app_wires_tour_entrypoints():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "from ui.tour import" in text
    assert "start_tour()" in text
    assert "render_tour()" in text
    assert "render_help_expander()" in text


def test_evaluation_screen_has_evaluator_dropdown_and_ground_truth():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "_evaluator_options" in text
    assert 'selectbox("Evaluator"' in text
    assert 'text_input("Ground truth (optional)"' in text
    assert "ground_truth=" in text


def test_evaluation_screen_calls_introspection_for_evaluators():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "api.evaluators()" in text
