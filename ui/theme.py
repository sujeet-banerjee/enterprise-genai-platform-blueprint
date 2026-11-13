"""Responsive layout, density and theme tokens for the console (issue #156).

Pure module: no Streamlit or backend imports so the contract stays testable.
``ui/app.py`` only consumes the returned CSS and helpers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

DEFAULT_THEME = "Light"
DEFAULT_DENSITY = "Comfortable"
DEFAULT_TABLE_LAYOUT = "Table"

THEME_OPTIONS: Tuple[str, ...] = ("Light", "Dark", "High contrast")
DENSITY_OPTIONS: Tuple[str, ...] = ("Comfortable", "Compact")
TABLE_LAYOUT_OPTIONS: Tuple[str, ...] = ("Table", "Cards")

BREAKPOINTS: Tuple[Dict[str, Any], ...] = (
    {"name": "compact", "min_width": 0, "max_width": 639},
    {"name": "tablet", "min_width": 640, "max_width": 1023},
    {"name": "desktop", "min_width": 1024, "max_width": 1439},
    {"name": "wide", "min_width": 1440, "max_width": None},
)

THEMES: Dict[str, Dict[str, Any]] = {
    "Light": {
        "background": "#ffffff",
        "surface": "#f6f8fa",
        "text": "#1f2328",
        "muted": "#57606a",
        "border": "#d0d7de",
        "accent": "#0b5fff",
        "accent_text": "#ffffff",
        "focus": "#0b5fff",
        "success": "#1a7f37",
        "warning": "#9a6700",
        "danger": "#cf222e",
        "chart": ("#0b5fff", "#1a7f37", "#9a6700", "#cf222e", "#8250df", "#0969da"),
    },
    "Dark": {
        "background": "#0d1117",
        "surface": "#161b22",
        "text": "#e6edf3",
        "muted": "#9198a1",
        "border": "#30363d",
        "accent": "#4493f8",
        "accent_text": "#0d1117",
        "focus": "#4493f8",
        "success": "#3fb950",
        "warning": "#d29922",
        "danger": "#f85149",
        "chart": ("#4493f8", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#58a6ff"),
    },
    "High contrast": {
        "background": "#000000",
        "surface": "#000000",
        "text": "#ffffff",
        "muted": "#ffffff",
        "border": "#ffffff",
        "accent": "#ffff00",
        "accent_text": "#000000",
        "focus": "#00ffff",
        "success": "#00ff00",
        "warning": "#ffff00",
        "danger": "#ff5555",
        "chart": ("#ffff00", "#00ff00", "#00ffff", "#ff5555", "#ff99ff", "#ffffff"),
    },
}

DENSITIES: Dict[str, Dict[str, str]] = {
    "Comfortable": {
        "row_height": "2.25rem",
        "padding": "1rem",
        "gap": "1rem",
        "font_size": "1rem",
        "line_height": "1.45",
    },
    "Compact": {
        "row_height": "1.75rem",
        "padding": "0.5rem",
        "gap": "0.5rem",
        "font_size": "0.9rem",
        "line_height": "1.3",
    },
}

STATUS_TONES: Dict[str, str] = {
    "success": "success",
    "ok": "success",
    "allowed": "success",
    "allow": "success",
    "ready": "success",
    "pass": "success",
    "warning": "warning",
    "degraded": "warning",
    "redacted": "warning",
    "pending": "warning",
    "danger": "danger",
    "error": "danger",
    "failed": "danger",
    "failure": "danger",
    "block": "danger",
    "blocked": "danger",
    "deny": "danger",
    "denied": "danger",
}


def resolve_theme(value: Optional[str]) -> str:
    """Return a supported theme name, falling back to the default."""
    if isinstance(value, str):
        for name in THEME_OPTIONS:
            if value.strip().lower() == name.lower():
                return name
    return DEFAULT_THEME


def resolve_density(value: Optional[str]) -> str:
    """Return a supported density name, falling back to the default."""
    if isinstance(value, str):
        for name in DENSITY_OPTIONS:
            if value.strip().lower() == name.lower():
                return name
    return DEFAULT_DENSITY


def resolve_table_layout(value: Optional[str]) -> str:
    """Return a supported table layout, falling back to the default."""
    if isinstance(value, str):
        for name in TABLE_LAYOUT_OPTIONS:
            if value.strip().lower() == name.lower():
                return name
    return DEFAULT_TABLE_LAYOUT


def breakpoint_for_width(width: int) -> str:
    """Map a viewport width in pixels to a named breakpoint."""
    try:
        pixels = int(width)
    except (TypeError, ValueError):
        pixels = 0
    pixels = max(0, pixels)
    for entry in BREAKPOINTS:
        maximum = entry["max_width"]
        if pixels >= entry["min_width"] and (maximum is None or pixels <= maximum):
            return str(entry["name"])
    return "wide"


def theme_tokens(name: Optional[str]) -> Dict[str, Any]:
    """Return a copy of the token map for a theme name."""
    return dict(THEMES[resolve_theme(name)])


def density_tokens(name: Optional[str]) -> Dict[str, str]:
    """Return a copy of the spacing tokens for a density name."""
    return dict(DENSITIES[resolve_density(name)])


def status_color(name: Optional[str], theme: Optional[str] = None) -> str:
    """Map an outcome/status label to a semantic colour token."""
    key = (name or "").strip().lower()
    tone = STATUS_TONES.get(key)
    tokens = THEMES[resolve_theme(theme)]
    if tone is None:
        return str(tokens["muted"])
    return str(tokens[tone])


def chart_palette(name: Optional[str]) -> Tuple[str, ...]:
    """Return the semantic chart palette for a theme."""
    return tuple(THEMES[resolve_theme(name)]["chart"])


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance for a ``#rrggbb`` colour."""
    value = (color or "").strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected a #rrggbb colour, got {color!r}")
    red = _channel(int(value[0:2], 16) / 255.0)
    green = _channel(int(value[2:4], 16) / 255.0)
    blue = _channel(int(value[4:6], 16) / 255.0)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def theme_contrast_rows(theme: Optional[str] = None) -> List[Dict[str, Any]]:
    """Contrast evidence for the documentation and tests."""
    tokens = THEMES[resolve_theme(theme)]
    rows = []
    for key in ("text", "muted", "accent", "success", "warning", "danger"):
        rows.append(
            {
                "token": key,
                "colour": tokens[key],
                "background": tokens["background"],
                "ratio": round(contrast_ratio(tokens[key], tokens["background"]), 2),
            }
        )
    return rows


def table_to_cards(
    rows: Sequence[Mapping[str, Any]],
    columns: Optional[Sequence[str]] = None,
    title_columns: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Map tabular rows to cards, preserving every column (including actions).

    The first non-empty value from ``title_columns`` (default: the first
    column) becomes the card title; every column still appears in ``fields``
    so no action or value is dropped when a narrow viewport degrades a table.
    """
    materialised = [dict(row) for row in rows or []]
    if not materialised:
        return []
    keys: List[str] = list(columns) if columns else []
    if not keys:
        for row in materialised:
            for key in row:
                if key not in keys:
                    keys.append(str(key))
    title_keys = [str(key) for key in (title_columns or keys[:1])]
    cards: List[Dict[str, Any]] = []
    for row in materialised:
        title = ""
        for key in title_keys:
            value = row.get(key)
            if value not in (None, ""):
                title = str(value)
                break
        fields = [{"label": str(key), "value": _display(row.get(key))} for key in keys]
        cards.append({"title": title or "Item", "fields": fields})
    return cards


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def styles(
    theme: Optional[str] = None,
    density: Optional[str] = None,
) -> str:
    """Return the responsive/density/theme stylesheet injected per render."""
    name = resolve_theme(theme)
    spacing = DENSITIES[resolve_density(density)]
    tokens = THEMES[name]
    palette = ", ".join(tokens["chart"])
    return f"""
<style>
:root {{
  --genai-bg: {tokens["background"]};
  --genai-surface: {tokens["surface"]};
  --genai-text: {tokens["text"]};
  --genai-muted: {tokens["muted"]};
  --genai-border: {tokens["border"]};
  --genai-accent: {tokens["accent"]};
  --genai-accent-text: {tokens["accent_text"]};
  --genai-focus: {tokens["focus"]};
  --genai-success: {tokens["success"]};
  --genai-warning: {tokens["warning"]};
  --genai-danger: {tokens["danger"]};
  --genai-chart: {palette};
  --genai-gap: {spacing["gap"]};
  --genai-padding: {spacing["padding"]};
  --genai-row-height: {spacing["row_height"]};
  --genai-font-size: {spacing["font_size"]};
  --genai-line-height: {spacing["line_height"]};
}}
.stApp {{
  background: var(--genai-bg);
  color: var(--genai-text);
  font-size: var(--genai-font-size);
  line-height: var(--genai-line-height);
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: var(--genai-text); }}
.stApp p, .stApp li, .stApp label, .stApp span {{ color: inherit; }}
[data-testid="stSidebar"] {{
  background: var(--genai-surface);
  border-right: 1px solid var(--genai-border);
}}
[data-testid="stVerticalBlock"] {{ gap: var(--genai-gap); }}
.stButton > button, [data-testid="stFormSubmitButton"] > button {{
  padding-top: calc(var(--genai-padding) * 0.35);
  padding-bottom: calc(var(--genai-padding) * 0.35);
}}
.stButton > button:focus-visible, [data-testid="stFormSubmitButton"] > button:focus-visible {{
  outline: 3px solid var(--genai-focus);
  outline-offset: 2px;
}}
.stDataFrame, [data-testid="stTable"] {{ font-size: var(--genai-font-size); }}
.stDataFrame [role="row"] {{ min-height: var(--genai-row-height); }}
.genai-card {{
  border: 1px solid var(--genai-border);
  border-radius: 0.5rem;
  padding: var(--genai-padding);
  margin-bottom: var(--genai-gap);
  background: var(--genai-surface);
}}
.genai-card h4 {{ margin: 0 0 0.35rem 0; font-size: 1rem; color: var(--genai-text); }}
.genai-card dl {{ margin: 0; display: grid; grid-template-columns: minmax(6rem, 30%) 1fr; gap: 0.15rem 0.75rem; }}
.genai-card dt {{ color: var(--genai-muted); font-size: 0.85rem; }}
.genai-card dd {{ margin: 0; word-break: break-word; }}
.genai-status {{ font-weight: 600; }}
@media (min-width: 1024px) {{
  [data-testid="stSidebar"] > div:first-child {{
    position: sticky;
    top: 0;
    max-height: 100vh;
    overflow-y: auto;
  }}
}}
@media (max-width: 1023px) {{
  .stApp .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
  .genai-card dl {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 640px) {{
  .stApp .block-container {{ padding-left: 0.5rem; padding-right: 0.5rem; }}
  .stApp h1 {{ font-size: 1.5rem; }}
  .stApp h2 {{ font-size: 1.25rem; }}
  .stApp [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  .stApp .stDataFrame {{ overflow-x: auto; }}
  .genai-card {{ padding: 0.5rem; }}
}}
</style>
"""
