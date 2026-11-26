import ast
import json
from pathlib import Path

import pytest

from ui import trust_view

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "ui" / "app.py"
TRUST_VIEW = REPO / "ui" / "trust_view.py"
THEME = REPO / "ui" / "theme.py"
PLAN = REPO / "docs" / "ui-enterprise-look-and-feel-plan.md"
WIRE_EXCALIDRAW = REPO / "docs" / "wireframes" / "256-trust-actions-progress.excalidraw"
WIRE_SVG = REPO / "docs" / "wireframes" / "256-trust-actions-progress.svg"


@pytest.mark.parametrize(
    ("kind", "tone"),
    [
        ("demo", "warning"),
        ("redacted", "info"),
        ("read_only", "info"),
        ("tenant_scoped", "warning"),
        ("admin_confirm", "warning"),
        ("destructive", "danger"),
    ],
)
def test_trust_banner_model_maps_every_mode(kind, tone):
    banner = trust_view.trust_banner_model(kind, detail="note", scope="tenant-a")
    assert banner["kind"] == kind
    assert banner["tone"] == tone
    assert banner["message"]
    assert banner["detail"] == "note"
    assert banner["scope"] == "tenant-a"


def test_trust_banner_unknown_mode_falls_back_to_redacted():
    banner = trust_view.trust_banner_model("not-a-mode")
    assert banner["kind"] == "redacted"
    assert banner["title"] == "Redacted view"


def test_trust_banner_markdown_escapes_and_redacts_mapping_detail():
    banner = trust_view.trust_banner_model(
        "redacted",
        detail={"request_id": "req-1", "api_key": "sk-SECRET"},
    )
    html = trust_view.trust_banner_markdown(banner)
    assert 'role="status"' in html
    assert "genai-trust-banner-info" in html
    assert "[REDACTED]" in html
    assert "sk-SECRET" not in html
    assert "&lt;script&gt;" not in html


def test_trust_banner_markdown_escapes_untrusted_text():
    banner = trust_view.trust_banner_model("demo", detail="<script>bad()</script>")
    html = trust_view.trust_banner_markdown(banner)
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


@pytest.mark.parametrize(
    ("hierarchy", "expected_type"),
    [
        ("primary", "primary"),
        ("secondary", "secondary"),
        ("destructive", "secondary"),
        ("admin", "secondary"),
        ("unknown", "secondary"),
    ],
)
def test_action_model_normalizes_hierarchy(hierarchy, expected_type):
    action = trust_view.action_model("Continue", hierarchy)
    assert action["hierarchy"] == ("secondary" if hierarchy == "unknown" else hierarchy)
    assert action["type"] == expected_type
    assert action["label"] == "Continue"


def test_button_kwargs_and_confirmation_copy_follow_hierarchy():
    primary = trust_view.button_kwargs(trust_view.action_model("Run query", "primary", "tip"))
    destructive = trust_view.action_model("Cancel job", "destructive")
    admin = trust_view.action_model("Update tenant", "admin")
    assert primary == {"type": "primary", "help": "tip"}
    assert trust_view.button_kwargs(destructive) == {"type": "secondary"}
    assert "cannot be undone" in trust_view.confirmation_copy(destructive)
    assert "audit" in trust_view.confirmation_copy(admin)
    assert trust_view.confirmation_copy(primary) == ""


def test_action_markdown_escapes_label():
    html = trust_view.action_markdown(
        trust_view.action_model("<img src=x>", "destructive")
    )
    assert "genai-action-destructive" in html
    assert "&lt;img" in html
    assert "<img" not in html


def test_progress_model_computes_bounded_percent_and_text():
    progress = trust_view.progress_model("eval_job", 3, 4, "running", "case 3")
    assert progress["kind"] == "eval_job"
    assert progress["fraction"] == pytest.approx(0.75)
    assert progress["percent"] == 75
    assert "75%" in progress["text"]
    assert progress["detail"] == "case 3"
    over = trust_view.progress_model("batch", 99, 10)
    assert over["percent"] == 100
    done = trust_view.progress_model("rebuild", 1, 1, "completed")
    assert done["text"].startswith("Completed:")


def test_progress_model_ignores_invalid_totals():
    progress = trust_view.progress_model("query", 3, 0)
    assert progress["fraction"] is None
    assert progress["percent"] is None
    assert "Running query..." in progress["text"]


def test_progress_markdown_renders_fill_and_escapes_detail():
    progress = trust_view.progress_model("eval_job", 1, 2, detail="<b>ok</b>")
    html = trust_view.progress_markdown(progress)
    assert 'role="status"' in html
    assert "genai-progress-fill" in html
    assert "width:50%" in html
    assert "&lt;b&gt;ok&lt;/b&gt;" in html
    assert "<b>" not in html


def test_progress_markdown_uses_skeleton_without_fraction():
    html = trust_view.progress_markdown(trust_view.progress_model("rebuild"))
    assert "genai-progress-skeleton" in html
    assert "genai-progress-fill" not in html


def test_trust_view_module_stays_pure_and_http_only():
    tree = ast.parse(TRUST_VIEW.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert "streamlit" not in modules
    assert "requests" not in modules
    assert not any(module.startswith("app.") or module.startswith("core.") for module in modules)


def test_app_wires_all_trust_banner_modes():
    source = APP.read_text(encoding="utf-8")
    assert "from ui.trust_view import (" in source
    for kind in (
        "demo",
        "redacted",
        "read_only",
        "tenant_scoped",
        "admin_confirm",
        "destructive",
    ):
        assert f'_render_trust_banner("{kind}"' in source


def test_app_wires_action_hierarchy_and_confirmation_helpers():
    source = APP.read_text(encoding="utf-8")
    assert "_render_action_hint(" in source
    assert source.count("action_model(") >= 6
    for label in (
        "Run query",
        "Apply what-if & run",
        "Cancel job",
        "Remove from history",
        "Update tenant",
        "Submit decision",
    ):
        assert f'"{label}"' in source
    assert '"admin",' in source
    assert '"destructive",' in source


def test_app_wires_loading_and_progress_cues():
    source = APP.read_text(encoding="utf-8")
    for kind in ("batch", "query", "rebuild", "approvals"):
        assert f'_render_progress("{kind}"' in source
    assert 'progress_model(\n        "eval_job",' in source
    assert "progress_markdown(eval_progress)" in source


def test_theme_defines_trust_action_and_progress_styles():
    css = THEME.read_text(encoding="utf-8")
    for token in (
        ".genai-trust-banner",
        ".genai-trust-banner-danger",
        ".genai-action-primary",
        ".genai-action-destructive",
        ".genai-progress-track",
        ".genai-progress-fill",
        ".genai-progress-skeleton",
    ):
        assert token in css


def test_wireframe_and_plan_index_are_committed():
    assert WIRE_EXCALIDRAW.exists()
    assert WIRE_SVG.exists()
    scene = json.loads(WIRE_EXCALIDRAW.read_text(encoding="utf-8"))
    assert scene["type"] == "excalidraw"
    texts = " ".join(str(item.get("text", "")) for item in scene["elements"])
    assert "Trust banners, actions and progress - #256" in texts
    svg = WIRE_SVG.read_text(encoding="utf-8")
    assert 'viewBox="0 0 1184 744"' in svg
    plan = PLAN.read_text(encoding="utf-8")
    assert "256-trust-actions-progress.svg" in plan
    assert "256-trust-actions-progress.excalidraw" in plan
