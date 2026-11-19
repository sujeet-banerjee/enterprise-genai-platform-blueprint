import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ui import components
from ui.polish import error_remediation
from ui.theme import styles

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "ui" / "app.py"
COMMON = REPO / "ui" / "common.py"
COMPONENTS = REPO / "ui" / "components.py"
PLAN = REPO / "docs" / "ui-enterprise-look-and-feel-plan.md"
WIRE_EXCALIDRAW = REPO / "docs" / "wireframes" / "241-design-system-primitives.excalidraw"
WIRE_SVG = REPO / "docs" / "wireframes" / "241-design-system-primitives.svg"


@pytest.mark.parametrize(
    ("status", "tone"),
    [
        ("ok", "success"),
        ("warning", "warning"),
        ("blocked", "danger"),
        ("pending", "warning"),
        ("disabled", "neutral"),
        ("something-new", "neutral"),
    ],
)
def test_badge_model_maps_semantic_statuses(status, tone):
    badge = components.badge_model(status)
    assert badge["status"] == status
    assert badge["tone"] == tone
    assert badge["label"] == status
    assert badge["color"]


def test_badge_markdown_uses_tone_and_escapes_label():
    html = components.badge_markdown(components.badge_model("ok", "<script>bad()</script>"))
    assert "genai-chip-success" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_kpi_strip_skips_bad_entries_and_renders_status():
    rows = components.kpi_strip(
        [
            {"label": "Requests", "value": 1234, "status": "ok"},
            "not-a-mapping",
            {"label": "Latency", "value": 184.2, "status": "warning", "hint": "p95"},
        ]
    )
    assert len(rows) == 2
    html = components.kpi_strip_markdown(rows)
    assert "genai-kpi-strip" in html
    assert "1,234" in html
    assert "genai-chip-warning" in html
    assert "p95" in html


def test_kpi_strip_handles_empty_input():
    assert "No metrics available" in components.kpi_strip_markdown([])


def test_key_value_rows_redact_secret_keys_and_nested_payloads():
    rows = components.key_value_rows(
        {
            "request_id": "req-123",
            "api_token": "super-secret",
            "config": {"password": "hunter2", "region": "us-east-1"},
            "latency_ms": None,
        },
        labels={"request_id": "Request ID"},
    )
    by_label = {row["label"]: row["value"] for row in rows}
    assert by_label["Request ID"] == "req-123"
    assert by_label["Api Token"] == "[REDACTED]"
    assert "super-secret" not in str(rows)
    assert "hunter2" not in str(rows)
    assert "us-east-1" in by_label["Config"]
    assert by_label["Latency Ms"] == "-"


def test_key_value_markdown_escapes_values():
    html = components.key_value_markdown(
        [{"label": "note", "value": "<img src=x onerror=alert(1)>"}]
    )
    assert "&lt;img" in html
    assert "<img" not in html


def test_section_card_markdown_renders_description_actions_and_body():
    card = components.section_card_model(
        "Governance snapshot",
        description="Cost and denials",
        body_html="<p class=\"genai-muted\">Curated</p>",
        actions=["Open trace", None, "View policy"],
    )
    html = components.section_card_markdown(card)
    assert "genai-section-card" in html
    assert "Cost and denials" in html
    assert "Curated" in html
    assert "genai-actions" in html
    assert "Open trace" in html
    assert "View policy" in html


def test_detail_drawer_keeps_summary_and_redacts_payload():
    drawer = components.detail_drawer_model(
        "Retrieval summary",
        {"documents": 6, "top_k": 5},
        {"docs": [{"api_key": "sk-secret", "content": "safe"}], "token": "abc"},
    )
    html = components.detail_drawer_markdown(drawer)
    assert drawer["payload"]["docs"][0]["api_key"] == "[REDACTED]"
    assert drawer["payload"]["token"] == "[REDACTED]"
    assert "sk-secret" not in str(drawer)
    assert "Documents" in html
    assert "Raw payload (redacted)" in html


def test_alert_markdown_includes_taxonomy_tags_and_request_id():
    html = components.alert_markdown(
        components.alert_model(
            "Service not ready",
            message="Retry shortly",
            failure_type="not_ready",
            tags=["startup", "<b>x</b>"],
            request_id="req-99",
            hint="Check /ready",
            action="Retry request",
            tone="warning",
        )
    )
    assert "genai-alert-warning" in html
    assert "not_ready" in html
    assert "startup" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "req-99" in html
    assert "Check /ready" in html
    assert "Retry request" in html


def test_failure_alert_model_uses_remediation():
    alert = components.failure_alert_model(503, "not_ready", ["startup"], "req-1", "still booting")
    expected = error_remediation(503, "not_ready")
    assert alert["title"] == expected["title"]
    assert alert["hint"] == expected["hint"]
    assert alert["action"] == expected["action"]
    assert alert["tone"] == "danger"
    assert alert["tags"] == ["startup"]


def test_error_alert_model_handles_api_result_like_object():
    result = SimpleNamespace(
        ok=False,
        status_code=403,
        failure_type="guardrail_input_blocked",
        failure_tags=["guardrail", "injection"],
        request_id="req-7",
        data={"error": "blocked by policy"},
        error=None,
    )
    alert = components.error_alert_model(result)
    assert alert["failure_type"] == "guardrail_input_blocked"
    assert alert["message"] == "blocked by policy"
    assert alert["tags"] == ["guardrail", "injection"]
    assert alert["request_id"] == "req-7"
    assert alert["tone"] == "warning"


def test_error_alert_model_falls_back_to_error_text():
    result = SimpleNamespace(
        status_code=0,
        failure_type="",
        failure_tags=[],
        request_id="",
        data={},
        error="network down",
    )
    alert = components.error_alert_model(result)
    assert alert["message"] == "network down"
    assert alert["failure_type"] == "unknown_failure"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (174.2, "174.2 ms"),
        (0.5, "0.50 ms"),
        (1500, "1.50 s"),
        (None, "-"),
        ("bad", "-"),
    ],
)
def test_format_duration_ms(value, expected):
    assert components.format_duration_ms(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12.4300, "$12.43"),
        (0.01234, "$0.0123"),
        ("$1,234.5", "$1,234.50"),
        (None, "-"),
        ("bad", "-"),
    ],
)
def test_format_cost_usd(value, expected):
    assert components.format_cost_usd(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12345, "12,345"),
        ("7.9", "7"),
        (None, "0"),
        (True, "0"),
    ],
)
def test_format_count(value, expected):
    assert components.format_count(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "Yes"),
        (False, "No"),
        ("YES", "Yes"),
        ("off", "No"),
        ("maybe", "-"),
    ],
)
def test_format_bool(value, expected):
    assert components.format_bool(value) == expected


def test_format_timestamp_normalizes_iso_epoch_and_odd_values():
    assert (
        components.format_timestamp(datetime(2026, 11, 19, 10, 30, tzinfo=timezone.utc))
        == "2026-11-19 10:30:00 UTC"
    )
    assert components.format_timestamp("2026-11-19T10:30:00Z") == "2026-11-19 10:30:00 UTC"
    assert components.format_timestamp(0) == "1970-01-01 00:00:00 UTC"
    assert components.format_timestamp("not-a-date") == "not-a-date"
    assert components.format_timestamp(None) == "-"


def test_theme_contains_component_primitives_css():
    css = styles("Light", "Comfortable")
    for token in (
        ".genai-kpi-strip",
        ".genai-kpi-value",
        ".genai-alert",
        ".genai-alert-warning",
        ".genai-card-description",
        ".genai-actions",
    ):
        assert token in css


def test_components_module_stays_pure_and_http_only():
    tree = ast.parse(COMPONENTS.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert "streamlit" not in modules
    assert not any(module.startswith("app.") or module.startswith("core.") for module in modules)


def test_common_routes_errors_through_structured_alert():
    source = COMMON.read_text(encoding="utf-8")
    assert "error_alert_model(result)" in source
    assert "alert_markdown(alert)" in source
    assert "st.error(" not in source


def test_app_wires_component_renderers_and_overview_uses_them():
    source = APP.read_text(encoding="utf-8")
    assert "from ui.components import (" in source
    assert "failure_alert_model(" in source
    assert "_render_kpi_strip(" in source
    assert "_render_detail_drawer(" in source
    tree = ast.parse(source)
    overview = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "screen_overview"
    )
    body = ast.get_source_segment(source, overview) or ""
    assert "_render_kpi_strip(kpis)" in body
    assert "_render_detail_drawer(" in body
    assert "st.metric(" not in body
    assert "st.json(" not in body


def test_wireframe_and_plan_index_are_committed():
    assert WIRE_EXCALIDRAW.exists()
    assert WIRE_SVG.exists()
    scene = WIRE_EXCALIDRAW.read_text(encoding="utf-8")
    svg = WIRE_SVG.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    assert '"name": "241-design-system-primitives"' in scene
    assert 'viewBox="0 0 1184 744"' in svg
    assert "241-design-system-primitives.svg" in plan
    assert "241-design-system-primitives.excalidraw" in plan
