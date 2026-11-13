"""UX12: command palette and accessibility contract (#155)."""

from __future__ import annotations

import ast
from pathlib import Path

from ui import a11y, palette


def _item(kind: str, label: str, target: str = "", **extra: str) -> palette.PaletteItem:
    return palette.PaletteItem(
        id=f"{kind}::{label}",
        label=label,
        kind=kind,
        target=target or label,
        category=extra.get("category", "Test"),
        keywords=extra.get("keywords", ""),
        help=extra.get("help", ""),
    )


def test_parse_query_prefixes_and_needle() -> None:
    assert palette.parse_query("") == palette.PaletteQuery(raw="", kind=None, needle="")
    assert palette.parse_query("  Traces ").kind is None
    assert palette.parse_query("/Traces").kind == "screen"
    assert palette.parse_query("/Traces").needle == "traces"
    assert palette.parse_query("> approve").kind == "action"
    assert palette.parse_query("> approve").needle == "approve"
    assert palette.parse_query("#req-1").kind == "request"
    assert palette.parse_query("#req-1").needle == "req-1"
    assert palette.parse_query("@acme").kind == "tenant"
    assert palette.parse_query("@acme").needle == "acme"


def test_build_items_respects_capabilities_and_sources() -> None:
    screens = ["Overview / Health", "Query Studio", "Admin", "Approvals"]
    items = palette.build_items(
        screens,
        ["query"],
        recent_requests=["req-1", "req-1", "req-2"],
        tenants=["tenant-a", "tenant-a", ""],
    )
    labels = {item.label for item in items}
    assert "Overview / Health" in labels
    assert "Query Studio" in labels
    assert "Admin" not in labels
    assert "Approvals" not in labels
    assert "Run a query" in labels
    assert "Trace req-1" in labels and "Trace req-2" in labels
    assert "Tenant tenant-a" in labels
    assert "Keyboard shortcuts and accessibility" in labels
    assert [item.label for item in items].count("Trace req-1") == 1
    screen_items = [item for item in items if item.kind == "screen"]
    assert all(item.id.startswith("screen::") for item in screen_items)


def test_filter_items_ranks_exact_prefix_and_substring() -> None:
    items = [
        _item("screen", "Trace comparison"),
        _item("screen", "Traces"),
        _item("screen", "Open traces evidence", keywords="traces"),
        _item("action", "Unrelated"),
    ]
    ranked = palette.filter_items(items, "traces")
    assert ranked[0].label == "Traces"
    assert {item.label for item in ranked} == {
        "Traces",
        "Trace comparison",
        "Open traces evidence",
    }
    assert palette.filter_items(items, "/traces")[0].kind == "screen"
    assert palette.filter_items(items, "#traces") == []
    assert palette.filter_items(items, "zzz") == []


def test_filter_items_honours_kind_prefix_and_limit() -> None:
    items = [
        _item("screen", "Traces"),
        _item("request", "Trace req-1", target="req-1"),
        _item("request", "Trace req-2", target="req-2"),
    ]
    requests = palette.filter_items(items, "#trace")
    assert [item.target for item in requests] == ["req-1", "req-2"]
    assert len(palette.filter_items(items, "", limit=2)) == 2
    assert len(palette.filter_items(items, "", limit=0)) == 1


def test_resolve_action_maps_each_kind() -> None:
    assert palette.resolve_action(_item("screen", "Traces")) == {"screen": "Traces"}
    assert palette.resolve_action(_item("action", "Run a query", "Query Studio")) == {
        "screen": "Query Studio"
    }
    request = palette.resolve_action(_item("request", "Trace req-1", "req-1"))
    assert request == {"screen": "Traces", "request_id": "req-1"}
    tenant = palette.resolve_action(_item("tenant", "Tenant acme", "acme"))
    assert tenant == {"screen": "Governance & Cost", "tenant": "acme"}
    assert palette.resolve_action(_item("help", "Help")) == {"help": True}


def test_shortcut_registration_and_help_markdown() -> None:
    assert len(palette.SHORTCUTS) >= 6
    assert len({shortcut.action for shortcut in palette.SHORTCUTS}) == len(palette.SHORTCUTS)
    keys = " ".join(shortcut.keys for shortcut in palette.SHORTCUTS)
    assert "Ctrl+K" in keys and "Cmd+K" in keys
    assert "Enter" in keys and "Tab" in keys
    rows = palette.shortcut_rows()
    assert {"action", "keys", "scope"} <= set(rows[0])
    markdown = palette.shortcut_help_markdown()
    assert "Command palette" in markdown and "Ctrl+K" in markdown


def test_recent_request_ids_dedupes_and_caps() -> None:
    entries = [
        {"request_id": "req-1"},
        {"request_id": ""},
        {"request_id": "req-1"},
        {"request_id": "req-2"},
        {"query": "no id"},
    ]
    assert palette.recent_request_ids(entries) == ["req-1", "req-2"]
    many = [{"request_id": f"req-{index}"} for index in range(20)]
    assert len(palette.recent_request_ids(many)) == palette.MAX_RECENT_REQUESTS


def test_a11y_checklist_and_exceptions_contract() -> None:
    summary = a11y.checklist_summary()
    assert summary["total"] == len(a11y.WCAG_CHECKLIST)
    assert summary["meets"] == summary["total"]
    assert summary["complete"] is True
    assert summary["exceptions"] == len(a11y.KNOWN_EXCEPTIONS)
    assert all(row["owner"] for row in a11y.KNOWN_EXCEPTIONS)
    assert all(step[0].isdigit() for step in a11y.SCREEN_READER_SCRIPT)
    markdown = a11y.checklist_markdown()
    assert "WCAG 2.2 AA" in markdown and "Known exceptions" in markdown
    assert "Screen-reader test script" in markdown


def test_a11y_styles_cover_focus_reduced_motion_and_skip_link() -> None:
    css = a11y.styles()
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "animation-duration" in css
    html = a11y.skip_link_html()
    assert "Skip to main content" in html
    assert f'id="{a11y.SKIP_LINK_TARGET}"' in html
    assert "custom-target" in a11y.skip_link_html("#custom-target")
    assert "genai-sr-only" in a11y.sr_only("context")


def test_palette_and_a11y_modules_are_pure() -> None:
    for path in ("ui/palette.py", "ui/a11y.py"):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        assert "app" not in modules, path
        assert "core" not in modules, path
        assert "streamlit" not in modules, path
        assert "requests" not in modules, path


def test_app_wires_palette_skip_link_and_help() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {
        "_palette_dialog",
        "_shortcuts_dialog",
        "_palette_from_query",
        "_apply_palette_item",
        "_palette_items",
        "_open_shortcuts",
    } <= functions
    for token in (
        "@st.dialog(\"Command palette\")",
        "@st.dialog(\"Keyboard shortcuts and accessibility\")",
        "a11y_styles",
        "skip_link_html",
        "palette_open",
        "show_shortcuts",
        "palette_param_consumed",
        "Command palette (Ctrl+K)",
        "Keyboard shortcuts",
        "known_tenants",
        "st.form(\"palette_form\"",
        "st.text_input(",
    ):
        assert token in source, token


def test_accessibility_doc_records_prefixes_and_checklist() -> None:
    text = Path("docs/accessibility.md").read_text(encoding="utf-8")
    for token in (
        "# Console accessibility decision record",
        "`/` screen",
        "`#` request id",
        "Ctrl+K",
        "WCAG 2.2 AA checklist",
        "Known exceptions",
        "Screen-reader test script",
        "prefers-reduced-motion",
    ):
        assert token in text, token
