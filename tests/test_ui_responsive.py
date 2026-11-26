"""UX15: responsive table/card parity across console screens (#255)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from ui import responsive, theme


def test_responsive_view_preserves_every_column_and_action() -> None:
    rows = [
        {"request_id": "req-1", "status": "pending", "Actions": "Review"},
        {"request_id": "req-2", "status": "done", "Actions": "Open"},
    ]
    view = responsive.responsive_table_view(
        rows, columns=["request_id", "status", "Actions"], title_columns=["request_id"]
    )
    assert view["columns"] == ["request_id", "status", "Actions"]
    assert view["cards"][0]["title"] == "req-1"
    for card, row in zip(view["cards"], rows):
        labels = [field["label"] for field in card["fields"]]
        assert labels == ["request_id", "status", "Actions"]
        assert [field["value"] for field in card["fields"]] == [
            str(row["request_id"]),
            str(row["status"]),
            str(row["Actions"]),
        ]


def test_responsive_view_accepts_existing_table_markdown() -> None:
    rows = [{"metric": "latency", "value": 12}]
    table = '<table class="genai-custom"><tr><td>latency</td></tr></table>'
    view = responsive.responsive_table_view(rows, table_markdown=table)
    assert view["table_markdown"] == table
    assert "metric" in view["columns"]
    assert "value" in view["columns"]


def test_responsive_markdown_emits_paired_table_and_cards() -> None:
    html = responsive.responsive_table_markdown(
        [{"request_id": "req-1", "status": "pending"}],
        title_columns=["request_id"],
        class_name="approvals queue",
        screen="approvals",
    )
    assert 'class="genai-responsive-table approvals-queue genai-density-approvals"' in html
    assert 'class="genai-responsive-table__table"' in html
    assert 'class="genai-responsive-table__cards"' in html
    assert "<th>Request id</th>" in html
    assert "<h4>req-1</h4>" in html
    assert "<dt>status</dt><dd>pending</dd>" in html


def test_responsive_markdown_escapes_row_values() -> None:
    html = responsive.responsive_table_markdown(
        [{"note": "<script>alert(1)</script>", "owner": "a&b"}]
    )
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "a&amp;b" in html


def test_responsive_markdown_handles_empty_rows() -> None:
    html = responsive.responsive_table_markdown([], class_name="empty-table")
    assert "No rows available." in html
    assert html.count("No rows available.") == 2


def test_compact_density_only_applies_to_operational_screens() -> None:
    assert responsive.compact_screen_class("Approvals") == "genai-density-approvals"
    assert responsive.compact_screen_class("audit") == "genai-density-audit"
    assert responsive.compact_screen_class("traces") == "genai-density-traces"
    assert responsive.compact_screen_class("admin") == "genai-density-admin"
    for screen in ("overview", "evaluation", "settings", None):
        assert responsive.compact_screen_class(screen) == ""


def test_theme_css_switching_and_compact_density_rules_exist() -> None:
    css = theme.styles("Light", "Compact")
    assert ".genai-responsive-table__table { display: none; }" in css
    assert ".genai-responsive-table__cards { display: grid; }" in css
    assert ".genai-responsive-table__cards { grid-template-columns: 1fr; }" in css
    for screen in ("approvals", "audit", "traces", "admin"):
        assert f".genai-density-{screen} .genai-card" in css
    assert ".genai-actions {" in css


def test_responsive_module_is_pure() -> None:
    source = Path("ui/responsive.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert not ({"streamlit", "app", "core", "requests"} & modules)
    assert "ui.theme" in modules or "ui" in modules


def test_app_wires_responsive_tables_into_operational_screens() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {
        "screen_approvals",
        "screen_audit",
        "screen_admin",
        "screen_traces",
        "screen_guardrails",
        "screen_governance",
    } <= functions
    assert "from ui.responsive import responsive_table_markdown" in source
    assert source.count("responsive_table_markdown(") >= 15
    admin_source = Path("ui/admin_view.py").read_text(encoding="utf-8")
    combined = source + admin_source
    for token in (
        'screen="approvals"',
        'screen="audit"',
        'screen="traces"',
        'screen="admin"',
        'class_name="approvals-queue"',
        'class_name="audit-timeline"',
        'class_name="trace-waterfall"',
        'class_name="guardrail-decision-history"',
    ):
        assert token in combined, token
    assert "st.dataframe(" not in source


def test_admin_view_wraps_dense_tables() -> None:
    source = Path("ui/admin_view.py").read_text(encoding="utf-8")
    assert "from ui.responsive import responsive_table_markdown" in source
    assert 'class_name="admin-users"' in source
    assert 'class_name="admin-audit"' in source


def test_wireframe_guard() -> None:
    svg = Path("docs/wireframes/255-responsive-density-parity.svg").read_text(encoding="utf-8")
    source = Path("docs/wireframes/255-responsive-density-parity.excalidraw")
    assert source.is_file()
    assert json.loads(source.read_text(encoding="utf-8"))["type"] == "excalidraw"
    assert 'viewBox="0 0 1184 744"' in svg
    assert "Responsive density parity" in svg
