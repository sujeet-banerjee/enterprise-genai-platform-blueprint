"""Pure responsive table/card helpers shared by dense console screens (issue #255).

No Streamlit or backend imports: screens pass rows (and optionally existing
HTML table markup) and receive paired table/card markup plus view models.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ui.theme import table_to_cards

OPERATIONAL_SCREENS: Sequence[str] = ("approvals", "audit", "traces", "admin")


def _slug(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def compact_screen_class(screen: Optional[str]) -> str:
    """Return a compact-density class for operational screens only."""
    slug = _slug(screen)
    return f"genai-density-{slug}" if slug in OPERATIONAL_SCREENS else ""


def _columns_for(
    rows: Sequence[Mapping[str, Any]], columns: Optional[Sequence[str]]
) -> List[str]:
    if columns:
        return [str(column) for column in columns]
    keys: List[str] = []
    for row in rows:
        for key in row:
            if str(key) not in keys:
                keys.append(str(key))
    return keys


def _label(column: str) -> str:
    return column.replace("_", " ").strip().capitalize() or "Value"


def _safe_class(value: str) -> str:
    return _slug(value)


def _table_html(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return '<div class="genai-card genai-muted">No rows available.</div>'
    header = "".join(f"<th>{escape(_label(column))}</th>" for column in columns)
    body: List[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{escape(str(row.get(column)) if row.get(column) is not None else '-')}</td>"
            for column in columns
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<table class="genai-table"><thead><tr>{header}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def _cards_html(cards: Sequence[Mapping[str, Any]]) -> str:
    if not cards:
        return '<div class="genai-card genai-muted">No rows available.</div>'
    rendered: List[str] = []
    for card in cards:
        title = escape(str(card.get("title") or "Item"))
        fields: List[str] = []
        for field in card.get("fields") or []:
            if not isinstance(field, Mapping):
                continue
            label = escape(str(field.get("label") or ""))
            value = escape(str(field.get("value") if field.get("value") is not None else "-"))
            fields.append(f"<dt>{label}</dt><dd>{value}</dd>")
        rendered.append(
            f'<div class="genai-card"><h4>{title}</h4><dl>{"".join(fields)}</dl></div>'
        )
    return "".join(rendered)


def responsive_table_view(
    rows: Sequence[Mapping[str, Any]],
    *,
    table_markdown: Optional[str] = None,
    columns: Optional[Sequence[str]] = None,
    title_columns: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build paired table/card view models from one row source."""
    materialised: List[Dict[str, Any]] = [dict(row) for row in rows or []]
    resolved_columns = _columns_for(materialised, columns)
    cards = table_to_cards(materialised, resolved_columns, title_columns)
    return {
        "rows": materialised,
        "columns": resolved_columns,
        "table_markdown": table_markdown or _table_html(materialised, resolved_columns),
        "cards": cards,
        "cards_markdown": _cards_html(cards),
    }


def responsive_table_markdown(
    rows: Sequence[Mapping[str, Any]],
    *,
    table_markdown: Optional[str] = None,
    columns: Optional[Sequence[str]] = None,
    title_columns: Optional[Sequence[str]] = None,
    class_name: str = "",
    screen: Optional[str] = None,
) -> str:
    """Render paired table/card markup with automatic breakpoint switching."""
    view = responsive_table_view(
        rows,
        table_markdown=table_markdown,
        columns=columns,
        title_columns=title_columns,
    )
    classes = ["genai-responsive-table", _safe_class(class_name), compact_screen_class(screen)]
    wrapper_class = " ".join(part for part in classes if part)
    return (
        f'<div class="{escape(wrapper_class)}">'
        f'<div class="genai-responsive-table__table">{view["table_markdown"]}</div>'
        f'<div class="genai-responsive-table__cards">{view["cards_markdown"]}</div>'
        "</div>"
    )


__all__ = [
    "OPERATIONAL_SCREENS",
    "compact_screen_class",
    "responsive_table_markdown",
    "responsive_table_view",
]
