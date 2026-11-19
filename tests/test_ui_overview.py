import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from ui import overview
from ui.theme import styles as theme_styles

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "ui" / "app.py"
OVERVIEW_MODULE = REPO_ROOT / "ui" / "overview.py"
WIRE_EXCALIDRAW = REPO_ROOT / "docs" / "wireframes" / "242-overview-health.excalidraw"
WIRE_SVG = REPO_ROOT / "docs" / "wireframes" / "242-overview-health.svg"
PLAN = REPO_ROOT / "docs" / "ui-enterprise-look-and-feel-plan.md"


@dataclass
class FakeResult:
    data: Dict[str, Any]
    ok: bool = True
    status_code: int = 200


def _health(ok: bool = True) -> FakeResult:
    return FakeResult({"status": "ok" if ok else "unavailable"}, ok=ok, status_code=200 if ok else 503)


def _ready(ok: bool = True) -> FakeResult:
    return FakeResult(
        {
            "status": "ready" if ok else "not_ready",
            "config_revision": "rev-42",
            "components": {"llm": {"provider": "local", "name": "qwen"}, "retriever": "faiss"},
        },
        ok=ok,
        status_code=200 if ok else 503,
    )


def _discovery() -> Dict[str, FakeResult]:
    return {
        "models": FakeResult({"active": "qwen"}),
        "retrievers": FakeResult({"default_retriever": "faiss"}),
        "rerankers": FakeResult({"enabled": False}),
        "evaluators": FakeResult({"enabled": True, "active_evaluator": "semantic"}),
    }


def test_active_label_handles_discovery_shapes():
    assert overview.active_label("Active model", {"active": "qwen"}) == "qwen"
    assert overview.active_label("Retriever", {"default_retriever": "faiss"}) == "faiss"
    assert overview.active_label("Reranker", {"enabled": False}) == "disabled"
    assert overview.active_label("Evaluator", {"active_evaluator": "semantic"}) == "semantic"
    assert overview.active_label("Reranker", {"enabled": True}) == "-"


def test_overview_kpis_include_health_revision_tenant_and_topology():
    access = {"tenant": {"id": "acme", "workspace": "core"}, "role": "architect", "enabled": True}
    kpis = overview.overview_kpis(_health(), _ready(), access, _discovery(), "https://api.example.com")
    by_label = {row["label"]: row for row in kpis}
    assert set(by_label) == {
        "API health",
        "Readiness",
        "Config revision",
        "Tenant",
        "Active model",
        "Retriever",
        "Reranker",
        "Evaluator",
    }
    assert by_label["Config revision"]["value"] == "rev-42"
    assert by_label["Tenant"]["value"] == "acme / core"
    assert by_label["Active model"]["value"] == "qwen"
    assert by_label["Reranker"]["value"] == "disabled"
    assert by_label["Reranker"]["status"]["label"] == "disabled"
    assert by_label["Tenant"]["status"]["tone"] == "neutral"
    assert "api.example.com" in by_label["Tenant"]["hint"]


def test_overview_kpis_mark_failed_discovery_as_unavailable():
    discovery = _discovery()
    discovery["models"] = FakeResult({}, ok=False, status_code=503)
    kpis = overview.overview_kpis(_health(), _ready(), {}, discovery)
    model = next(row for row in kpis if row["label"] == "Active model")
    assert model["value"] == "unavailable"
    assert model["status"]["tone"] == "danger"


def test_component_cards_are_structured_key_value_cards():
    cards = overview.component_cards(
        {"llm": {"provider": "local", "api_key": "sk-secret"}, "retriever": "faiss"}
    )
    assert [card["title"] for card in cards] == ["Llm", "Retriever"]
    assert {row["label"] for row in cards[0]["rows"]} == {"Provider", "Api Key"}
    html = overview.component_cards_markdown(cards)
    assert '<section class="genai-card genai-section-card">' in html
    assert "sk-secret" not in html
    assert "[REDACTED]" in html


def test_component_cards_empty_state_is_not_raw_json():
    html = overview.component_cards_markdown([])
    assert "No registered components" in html
    assert "{" not in html.replace("genai-card", "")


def test_raw_detail_drawer_uses_labeled_redacted_expander():
    health = FakeResult({"status": "ok", "nested": {"token": "secret-value"}})
    ready = _ready()
    drawer = overview.raw_detail_drawer(health, ready)
    assert drawer["expander_label"] == "Raw (redacted)"
    assert drawer["payload"]["health"]["nested"]["token"] == "[REDACTED]"
    assert drawer["payload"]["ready"]["config_revision"] == "rev-42"


def test_checklist_card_is_driven_by_flags_and_capabilities():
    done = {
        "backend": True,
        "query": True,
        "trace": False,
        "evaluate": False,
        "governance": False,
        "guardrails": False,
        "audit": False,
        "admin": False,
    }
    view = overview.checklist_card_view(done, ["query", "governance"])
    assert view["completed"] == 2
    assert view["total"] == 4
    assert view["progress"] == 0.5
    assert view["next"]["key"] == "trace"
    assert "Query Studio" in view["card_markdown"]
    assert "Admin" not in view["card_markdown"]


def test_checklist_card_complete_state_has_no_next_step():
    view = overview.checklist_card_view(
        {"backend": True, "query": True, "trace": True, "governance": True},
        ["query", "governance"],
    )
    assert view["complete"] is True
    assert view["next"] is None
    assert "All available steps complete" in view["card_markdown"]


def test_overview_module_is_pure_and_http_only():
    tree = ast.parse(OVERVIEW_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "streamlit" not in imported
    assert not any(module.startswith("app.") or module.startswith("core.") for module in imported)


def test_app_wires_overview_helpers_and_keeps_raw_payload_in_expander():
    source = APP.read_text(encoding="utf-8")
    assert "from ui.overview import (" in source
    tree = ast.parse(source)
    screen = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "screen_overview"
    )
    body = ast.get_source_segment(source, screen) or ""
    assert "_render_kpi_strip(kpis)" in body
    assert "component_cards_markdown(cards)" in body
    assert "raw_detail_drawer(health, ready)" in body
    assert "_render_detail_drawer(" in body
    assert "st.json(components" not in body
    assert "st.json(ready.data" not in body
    assert 'detail["expander_label"]' in body


def test_get_started_uses_structured_checklist_card():
    source = APP.read_text(encoding="utf-8")
    assert "checklist_status(done, capabilities)" in source
    assert "checklist_card_view(done, capabilities, statuses)" in source
    assert 'checklist["card_markdown"]' in source
    start = source.index("def _render_get_started")
    end = source.index("def screen_overview")
    assert "st.dataframe(" not in source[start:end]


def test_theme_styles_checklist_card():
    css = theme_styles("light", "comfortable")
    assert ".genai-checklist" in css
    assert ".genai-checklist-item" in css


def test_wireframe_and_plan_index_are_committed():
    assert WIRE_EXCALIDRAW.exists()
    assert WIRE_SVG.exists()
    scene = WIRE_EXCALIDRAW.read_text(encoding="utf-8")
    svg = WIRE_SVG.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    assert '"name": "242-overview-health"' in scene
    assert 'viewBox="0 0 1184 744"' in svg
    assert "242-overview-health.svg" in plan


@pytest.mark.parametrize("value", [None, "", {}, [], 0])
def test_component_cards_handles_empty_shapes(value: Optional[Any]):
    assert overview.component_cards(value) == []
