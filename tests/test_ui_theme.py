"""UX13: responsive layout, density and theme contract (#156)."""

from __future__ import annotations

import ast
from pathlib import Path

from ui import theme


def test_breakpoints_cover_mobile_tablet_desktop_and_wide() -> None:
    assert theme.breakpoint_for_width(0) == "compact"
    assert theme.breakpoint_for_width(375) == "compact"
    assert theme.breakpoint_for_width(639) == "compact"
    assert theme.breakpoint_for_width(640) == "tablet"
    assert theme.breakpoint_for_width(768) == "tablet"
    assert theme.breakpoint_for_width(1023) == "tablet"
    assert theme.breakpoint_for_width(1024) == "desktop"
    assert theme.breakpoint_for_width(1280) == "desktop"
    assert theme.breakpoint_for_width(1439) == "desktop"
    assert theme.breakpoint_for_width(1440) == "wide"
    assert theme.breakpoint_for_width(1920) == "wide"


def test_breakpoint_for_width_is_defensive() -> None:
    assert theme.breakpoint_for_width("768") == "tablet"
    assert theme.breakpoint_for_width(None) == "compact"
    assert theme.breakpoint_for_width(-10) == "compact"


def test_resolve_helpers_fall_back_and_ignore_case() -> None:
    assert theme.resolve_theme("dark") == "Dark"
    assert theme.resolve_theme("  HIGH CONTRAST ") == "High contrast"
    assert theme.resolve_theme("sepia") == theme.DEFAULT_THEME
    assert theme.resolve_theme(None) == theme.DEFAULT_THEME
    assert theme.resolve_density("compact") == "Compact"
    assert theme.resolve_density("airy") == theme.DEFAULT_DENSITY
    assert theme.resolve_table_layout("cards") == "Cards"
    assert theme.resolve_table_layout("") == theme.DEFAULT_TABLE_LAYOUT
    assert theme.DEFAULT_THEME in theme.THEME_OPTIONS
    assert theme.DEFAULT_DENSITY in theme.DENSITY_OPTIONS
    assert theme.DEFAULT_TABLE_LAYOUT in theme.TABLE_LAYOUT_OPTIONS


def test_every_theme_meets_wcag_aa_for_text_tokens() -> None:
    for name in theme.THEME_OPTIONS:
        for row in theme.theme_contrast_rows(name):
            assert row["ratio"] >= 4.5, (name, row)


def test_chart_palettes_are_distinct_and_readable() -> None:
    for name in theme.THEME_OPTIONS:
        palette = theme.chart_palette(name)
        assert len(palette) >= 6
        assert len(set(palette)) == len(palette)
        background = theme.theme_tokens(name)["background"]
        for colour in palette:
            assert theme.contrast_ratio(colour, background) >= 3.0, (name, colour)


def test_contrast_helpers_are_wcag_correct() -> None:
    assert theme.contrast_ratio("#ffffff", "#000000") == 21.0
    assert theme.contrast_ratio("#000000", "#000000") == 1.0
    assert theme.relative_luminance("#ffffff") > theme.relative_luminance("#808080")
    try:
        theme.relative_luminance("not-a-colour")
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("invalid colours must raise")


def test_status_colours_map_semantic_outcomes() -> None:
    assert theme.status_color("allowed", "Light") == theme.THEMES["Light"]["success"]
    assert theme.status_color("blocked", "Dark") == theme.THEMES["Dark"]["danger"]
    assert theme.status_color("pending", "Light") == theme.THEMES["Light"]["warning"]
    assert theme.status_color("unknown", "Light") == theme.THEMES["Light"]["muted"]
    assert theme.status_color(None, "High contrast") == theme.THEMES["High contrast"]["muted"]


def test_token_helpers_return_copies() -> None:
    tokens = theme.theme_tokens("Dark")
    tokens["background"] = "#123456"
    assert theme.THEMES["Dark"]["background"] != "#123456"
    spacing = theme.density_tokens("Compact")
    spacing["padding"] = "99rem"
    assert theme.DENSITIES["Compact"]["padding"] != "99rem"


def test_styles_carry_theme_density_and_responsive_rules() -> None:
    css = theme.styles("High contrast", "Compact")
    assert theme.THEMES["High contrast"]["background"] in css
    assert theme.THEMES["High contrast"]["accent"] in css
    assert theme.DENSITIES["Compact"]["padding"] in css
    assert "--genai-row-height" in css
    assert "max-width: 640px" in css
    assert "max-width: 1023px" in css
    assert "min-width: 1024px" in css
    assert ".genai-card" in css
    assert ":focus-visible" in css
    assert "overflow-x: auto" in css
    assert css.startswith("\n<style>") or css.startswith("<style>")


def test_table_to_cards_preserves_every_column_and_action() -> None:
    rows = [
        {
            "provider": "injection",
            "edge": "input",
            "decision": "block",
            "Actions": "Review",
        },
        {"provider": "", "edge": "output", "decision": "redact", "Actions": "Inspect"},
    ]
    cards = theme.table_to_cards(rows, title_columns=["provider", "edge"])
    assert len(cards) == 2
    assert cards[0]["title"] == "injection"
    assert cards[1]["title"] == "output"
    for card, row in zip(cards, rows):
        labels = [field["label"] for field in card["fields"]]
        assert labels == ["provider", "edge", "decision", "Actions"]
        values = [field["value"] for field in card["fields"]]
        assert values == [str(row[key]) for key in ("provider", "edge", "decision", "Actions")]


def test_table_to_cards_handles_empty_and_missing_values() -> None:
    assert theme.table_to_cards([]) == []
    cards = theme.table_to_cards(
        [{"name": None, "enabled": True, "count": 0}, {"name": "", "enabled": False, "count": 3}]
    )
    assert cards[0]["title"] == "Item"
    assert cards[0]["fields"] == [
        {"label": "name", "value": "-"},
        {"label": "enabled", "value": "yes"},
        {"label": "count", "value": "0"},
    ]
    assert cards[1]["fields"][1]["value"] == "no"
    columns = theme.table_to_cards([{"a": 1}], columns=["a", "b"])
    assert [field["label"] for field in columns[0]["fields"]] == ["a", "b"]
    assert columns[0]["fields"][1]["value"] == "-"


def test_app_wires_appearance_controls_and_card_degradation() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"_render_appearance_sidebar", "_render_card_rows"} <= functions
    for token in (
        "from ui.theme import",
        "theme_styles(",
        "table_to_cards(",
        "_render_appearance_sidebar()",
        'key="ui_theme"',
        'key="ui_density"',
        'key="ui_table_layout"',
        'st.session_state.get("ui_table_layout") == "Cards"',
        'initial_sidebar_state="auto"',
        "Appearance",
    ):
        assert token in source, token


def test_theme_module_is_pure() -> None:
    tree = ast.parse(Path("ui/theme.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert "app" not in modules
    assert "core" not in modules
    assert "streamlit" not in modules
    assert "requests" not in modules


def test_theme_tokens_are_documented() -> None:
    text = Path("docs/layout-and-theme.md").read_text(encoding="utf-8")
    for name in theme.THEME_OPTIONS:
        assert name in text, name
    for density in theme.DENSITY_OPTIONS:
        assert density in text, density
    assert "375" in text and "768" in text and "1280" in text
    assert "4.5:1" in text
    assert "genai-card" in text
