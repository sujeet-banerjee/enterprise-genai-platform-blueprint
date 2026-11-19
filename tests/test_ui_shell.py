import ast
from pathlib import Path

import pytest

from ui.shell import (
    DEFAULT_SCREEN,
    PAGE_ICON,
    PAGE_TITLE,
    PRODUCT_NAME,
    environment_label,
    header_markdown,
    header_view,
    health_view,
    scope_view,
    sidebar_brand_markdown,
)
from ui.theme import styles

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "ui" / "app.py"
SHELL = REPO / "ui" / "shell.py"


def test_brand_constants_are_stable():
    assert PRODUCT_NAME == "Enterprise GenAI Platform Console"
    assert PAGE_TITLE == PRODUCT_NAME
    assert PAGE_ICON.startswith(":material/")
    assert DEFAULT_SCREEN == "Overview / Health"


@pytest.mark.parametrize(
    ("base", "demo", "expected"),
    [
        ("http://localhost:8000", False, "local"),
        ("http://127.0.0.1:8010", False, "local"),
        ("https://console.example.com", False, "console.example.com"),
        ("anything", True, "demo"),
        ("", False, "local"),
    ],
)
def test_environment_label(base, demo, expected):
    assert environment_label(base, demo) == expected


def test_health_view_ready_when_both_endpoints_ok():
    view = health_view(
        {"ok": True, "status_code": 200, "data": {"status": "ok"}},
        {"ok": True, "status_code": 200, "data": {"status": "ready"}},
    )
    assert view["state"] == "ready"
    assert view["tone"] == "success"
    assert view["label"] == "ready"
    assert "health: ok" in view["detail"]


@pytest.mark.parametrize(
    ("health", "ready", "state", "tone"),
    [
        (
            {"ok": True, "data": {"status": "ok"}},
            {"ok": True, "data": {"status": "degraded"}},
            "degraded",
            "warning",
        ),
        (
            {"ok": True, "data": {"status": "ok"}},
            {"ok": False, "status_code": 503, "data": {"status": "not_ready"}},
            "starting",
            "warning",
        ),
        (
            {"ok": False, "status_code": 0},
            {"ok": True, "data": {"status": "ready"}},
            "degraded",
            "warning",
        ),
        (
            {"ok": False, "status_code": 0},
            {"ok": False, "status_code": 503},
            "offline",
            "danger",
        ),
    ],
)
def test_health_view_reflects_both_endpoints(health, ready, state, tone):
    view = health_view(health, ready)
    assert view["state"] == state
    assert view["tone"] == tone


def test_scope_view_normalizes_tenant_workspace_and_role():
    access = {
        "ok": True,
        "enabled": True,
        "role": "admin",
        "tenant": {"id": "acme", "workspace": "prod"},
    }
    view = scope_view(access, "local")
    assert view["scope"] == "acme / prod"
    assert view["tenant"] == "acme"
    assert view["workspace"] == "prod"
    assert view["rbac"] == "RBAC on"
    assert view["role"]


def test_scope_view_defaults_when_access_unavailable():
    view = scope_view({"ok": False}, "demo")
    assert view["scope"] == "default / default"
    assert view["rbac"] == "RBAC off"
    assert view["environment"] == "demo"


def test_header_view_combines_all_chips():
    view = header_view(
        "Traces",
        {"ok": True, "enabled": False, "role": "analyst", "tenant": {"id": "t1"}},
        {"ok": True, "data": {"status": "ok"}},
        {"ok": True, "data": {"status": "ready"}},
        "local",
        False,
    )
    assert view["product"] == PRODUCT_NAME
    assert view["screen_title"] == "Traces"
    assert view["scope"]["tenant"] == "t1"
    assert view["health"]["state"] == "ready"
    assert view["demo"] is False


def test_header_markdown_is_escaped_and_semantic():
    view = header_view(
        '<img src=x onerror="alert(1)">',
        {"ok": True, "enabled": True, "role": "admin", "tenant": {"id": "a&b"}},
        {"ok": False, "status_code": 0},
        {"ok": False, "status_code": 503},
        "demo",
        True,
    )
    html = header_markdown(view)
    assert PRODUCT_NAME in html
    assert "&lt;img" in html
    assert "onerror=&quot;" in html
    assert "<img" not in html
    assert "a&amp;b" in html
    assert "genai-dot-danger" in html
    assert "demo data" in html
    assert html.endswith("</div></div>")


def test_sidebar_brand_markdown_is_text_only():
    html = sidebar_brand_markdown()
    assert "genai-sidebar-brand" in html
    assert "GENAI" in html
    assert PRODUCT_NAME in html
    assert "<img" not in html


def test_theme_contains_shell_tokens_and_classes():
    css = styles("Light", "Comfortable")
    assert "--genai-font-h1" in css
    assert "--genai-font-caption" in css
    assert ".genai-app-header" in css
    assert ".genai-header-mark" in css
    assert ".genai-health-dot" in css
    assert ".genai-sidebar-brand" in css


def test_app_uses_brand_metadata_and_header():
    source = APP.read_text(encoding="utf-8")
    assert "page_title=PAGE_TITLE" in source
    assert "page_icon=PAGE_ICON" in source
    assert "header_markdown(" in source
    assert "sidebar_brand_markdown()" in source
    assert "st.sidebar.title(" not in source
    assert "st.header(" not in source


def test_app_wires_health_refresh_for_every_screen():
    source = APP.read_text(encoding="utf-8")
    assert "_render_app_header(" in source
    assert "shell_health = api.health()" in source
    assert "shell_ready = api.ready()" in source
    assert "st.session_state.shell_health" in source


def test_shell_module_stays_pure_and_http_only():
    tree = ast.parse(SHELL.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert "streamlit" not in modules
    assert not any(module.startswith("app.") or module.startswith("core.") for module in modules)
