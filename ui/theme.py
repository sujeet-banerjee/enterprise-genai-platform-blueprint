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

TYPOGRAPHY: Dict[str, str] = {
    "h1": "1.6rem",
    "h2": "1.25rem",
    "h3": "1.05rem",
    "body": "var(--genai-font-size)",
    "caption": "0.78rem",
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
    "redact": "warning",
    "pending": "warning",
    "danger": "danger",
    "error": "danger",
    "failed": "danger",
    "failure": "danger",
    "block": "danger",
    "blocked": "danger",
    "deny": "danger",
    "denied": "danger",
    "disabled": "muted",
    "off": "muted",
    "neutral": "muted",
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
  --genai-font-h1: {TYPOGRAPHY["h1"]};
  --genai-font-h2: {TYPOGRAPHY["h2"]};
  --genai-font-h3: {TYPOGRAPHY["h3"]};
  --genai-font-body: {TYPOGRAPHY["body"]};
  --genai-font-caption: {TYPOGRAPHY["caption"]};
}}
.stApp {{
  background: var(--genai-bg);
  color: var(--genai-text);
  font-size: var(--genai-font-body);
  line-height: var(--genai-line-height);
}}
.stApp h1 {{ font-size: var(--genai-font-h1); font-weight: 650; letter-spacing: -0.015em; }}
.stApp h2 {{ font-size: var(--genai-font-h2); font-weight: 620; letter-spacing: -0.01em; }}
.stApp h3 {{ font-size: var(--genai-font-h3); font-weight: 600; }}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: var(--genai-text); margin-top: 0; }}
.stApp p, .stApp li, .stApp label, .stApp span {{ color: inherit; }}
.stApp [data-testid="stCaptionContainer"], .genai-muted {{ color: var(--genai-muted); font-size: var(--genai-font-caption); }}
.genai-app-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--genai-gap);
  padding: calc(var(--genai-padding) * 0.75) var(--genai-padding);
  margin-bottom: var(--genai-gap);
  border: 1px solid var(--genai-border);
  border-radius: 0.6rem;
  background: var(--genai-surface);
}}
.genai-header-identity, .genai-header-titles, .genai-header-chips {{
  display: flex;
  align-items: center;
  gap: calc(var(--genai-gap) * 0.6);
}}
.genai-header-titles {{ flex-direction: column; align-items: flex-start; gap: 0.1rem; }}
.genai-header-mark, .genai-sidebar-mark {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.4rem;
  background: var(--genai-accent);
  color: var(--genai-accent-text);
  font-weight: 700;
  letter-spacing: 0.08em;
}}
.genai-header-mark {{ min-width: 3.25rem; height: 2.2rem; font-size: var(--genai-font-caption); }}
.genai-product-title {{ font-size: var(--genai-font-h2); font-weight: 650; color: var(--genai-text); }}
.genai-screen-title {{ font-size: var(--genai-font-caption); color: var(--genai-muted); }}
.genai-chip {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.22rem 0.55rem;
  border: 1px solid var(--genai-border);
  border-radius: 999px;
  font-size: var(--genai-font-caption);
  white-space: nowrap;
}}
.genai-chip-neutral {{ color: var(--genai-muted); background: var(--genai-bg); }}
.genai-chip-success {{ color: var(--genai-success); background: var(--genai-bg); }}
.genai-chip-warning {{ color: var(--genai-warning); background: var(--genai-bg); }}
.genai-chip-danger {{ color: var(--genai-danger); background: var(--genai-bg); }}
.genai-health-dot {{
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--genai-muted);
}}
.genai-dot-success {{ background: var(--genai-success); }}
.genai-dot-warning {{ background: var(--genai-warning); }}
.genai-dot-danger {{ background: var(--genai-danger); }}
.genai-sidebar-brand {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.35rem 0 0.75rem 0;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid var(--genai-border);
}}
.genai-sidebar-mark {{ min-width: 2.8rem; height: 1.8rem; font-size: 0.7rem; }}
.genai-sidebar-name {{ font-weight: 650; color: var(--genai-text); }}
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
.genai-card-description {{ color: var(--genai-muted); margin: 0 0 0.6rem 0; }}
.genai-actions {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }}
.genai-checklist {{ margin: 0; padding-left: 1.25rem; }}
.genai-checklist-item {{ margin: 0 0 0.45rem 0; line-height: 1.5; }}
.genai-action {{
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--genai-border);
  border-radius: 0.35rem;
  font-size: var(--genai-font-caption);
}}
.genai-kpi-strip {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: var(--genai-gap);
  margin-bottom: var(--genai-gap);
}}
.genai-kpi {{
  border: 1px solid var(--genai-border);
  border-radius: 0.5rem;
  padding: var(--genai-padding);
  background: var(--genai-surface);
  min-height: 5.25rem;
}}
.genai-kpi-label {{ color: var(--genai-muted); font-size: var(--genai-font-caption); }}
.genai-kpi-value {{ font-size: 1.35rem; font-weight: 700; margin: 0.15rem 0; }}
.genai-kpi-meta {{ display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; font-size: var(--genai-font-caption); }}
.genai-kpi-delta {{ font-weight: 600; color: var(--genai-text); }}
.genai-alert {{
  border: 1px solid var(--genai-border);
  border-left: 4px solid var(--genai-muted);
  border-radius: 0.5rem;
  padding: var(--genai-padding);
  margin-bottom: var(--genai-gap);
  background: var(--genai-surface);
}}
.genai-alert-danger {{ border-left-color: var(--genai-danger); }}
.genai-alert-warning {{ border-left-color: var(--genai-warning); }}
.genai-alert-success {{ border-left-color: var(--genai-success); }}
.genai-alert-info {{ border-left-color: var(--genai-accent); }}
.genai-alert-title {{ font-weight: 700; margin-bottom: 0.25rem; }}
.genai-alert-message {{ margin-bottom: 0.4rem; }}
.genai-alert-meta {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.4rem; }}
.genai-alert-code, .genai-alert-request code {{
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: var(--genai-font-caption);
}}
.genai-alert-hint {{ color: var(--genai-muted); }}
.genai-alert-action {{ font-weight: 600; margin-top: 0.25rem; }}
.genai-query-badges {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.6rem; }}
.genai-query-answer {{ white-space: pre-wrap; line-height: 1.5; }}
.genai-query-failure {{ color: var(--genai-danger); font-weight: 600; }}
.genai-latency-chart {{ margin-bottom: var(--genai-gap); }}
.genai-score-line, .genai-latency-row {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0.35rem 0;
}}
.genai-latency-label {{ min-width: 8rem; }}
.genai-latency-value {{ min-width: 8rem; text-align: right; color: var(--genai-muted); font-size: var(--genai-font-caption); }}
.genai-score-track {{
  display: inline-block;
  flex: 1;
  min-width: 6rem;
  height: 0.55rem;
  border: 1px solid var(--genai-border);
  border-radius: 999px;
  background: var(--genai-bg);
  overflow: hidden;
}}
.genai-score-fill {{
  display: block;
  height: 100%;
  background: var(--genai-accent);
  border-radius: 999px;
}}
.genai-compare-table {{ width: 100%; border-collapse: collapse; }}
.genai-compare-table th, .genai-compare-table td {{
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--genai-border);
  text-align: left;
  vertical-align: top;
}}
.genai-delta-better {{ color: var(--genai-success); font-weight: 600; }}
.genai-delta-worse {{ color: var(--genai-danger); font-weight: 600; }}
.genai-delta-neutral {{ color: var(--genai-muted); }}
.genai-status {{ font-weight: 600; }}
.genai-waterfall-table, .genai-diff-table {{ width: 100%; border-collapse: collapse; }}
.genai-waterfall-table th, .genai-waterfall-table td,
.genai-diff-table th, .genai-diff-table td {{
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--genai-border);
  text-align: left;
  vertical-align: top;
}}
.genai-diff-cards {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}}
.genai-diff-cards .genai-card {{ height: 100%; }}
.genai-diff-table th {{ color: var(--genai-muted); font-weight: 600; }}
.genai-eval-matrix td.genai-metric-best {{ color: var(--genai-success); font-weight: 600; }}
.genai-waterfall-stage {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: var(--genai-font-caption); }}
.genai-waterfall-track {{
  display: block;
  min-width: 6rem;
  height: 0.5rem;
  border: 1px solid var(--genai-border);
  border-radius: 999px;
  background: var(--genai-bg);
  overflow: hidden;
}}
.genai-waterfall-fill {{
  display: block;
  height: 100%;
  background: var(--genai-accent);
  border-radius: 999px;
}}
.genai-cost-chart, .genai-failure-chart, .genai-guardrail-chart {{ display: grid; gap: 0.45rem; }}
.genai-cost-row, .genai-failure-row, .genai-guardrail-row {{
  display: grid;
  grid-template-columns: minmax(6rem, 10rem) 1fr auto;
  gap: 0.6rem;
  align-items: center;
  font-size: var(--genai-font-caption);
}}
.genai-cost-label, .genai-failure-label, .genai-guardrail-label {{
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  overflow-wrap: anywhere;
}}
.genai-cost-track, .genai-failure-track, .genai-guardrail-track {{
  display: flex;
  min-width: 5rem;
  height: 0.6rem;
  border: 1px solid var(--genai-border);
  border-radius: 999px;
  background: var(--genai-bg);
  overflow: hidden;
}}
.genai-cost-fill, .genai-failure-fill {{
  display: block;
  height: 100%;
  background: var(--genai-accent);
  border-radius: 999px;
}}
.genai-failure-fill {{ background: var(--genai-danger); }}
.genai-cost-value, .genai-failure-value, .genai-guardrail-value {{
  min-width: 5rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}}
.genai-guardrail-segment {{ display: block; height: 100%; }}
.genai-guardrail-allow {{ background: var(--genai-success); }}
.genai-guardrail-redact {{ background: var(--genai-warning); }}
.genai-guardrail-block {{ background: var(--genai-danger); }}
.genai-guardrail-legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.45rem;
  font-size: var(--genai-font-caption);
  color: var(--genai-muted);
}}
.genai-guardrail-legend-item {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
.genai-guardrail-legend-item::before {{
  content: "";
  display: inline-block;
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 2px;
}}
.genai-guardrail-legend-item.genai-guardrail-allow::before {{ background: var(--genai-success); }}
.genai-guardrail-legend-item.genai-guardrail-redact::before {{ background: var(--genai-warning); }}
.genai-guardrail-legend-item.genai-guardrail-block::before {{ background: var(--genai-danger); }}
.genai-guardrail-chain {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem;
}}
.genai-guardrail-edge {{
  border: 1px solid var(--genai-border);
  border-radius: 0.5rem;
  padding: 0.75rem;
  background: var(--genai-surface);
}}
.genai-guardrail-edge h4 {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.6rem;
}}
.genai-guardrail-count {{
  font-size: var(--genai-font-caption);
  font-weight: 400;
  color: var(--genai-muted);
}}
.genai-guardrail-node {{
  display: inline-flex;
  align-items: flex-start;
  gap: 0.5rem;
  vertical-align: top;
  max-width: 100%;
}}
.genai-guardrail-node + .genai-guardrail-arrow {{
  display: inline-flex;
  align-items: center;
  padding: 0 0.35rem;
  color: var(--genai-muted);
}}
.genai-guardrail-order {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  flex: 0 0 1.4rem;
  border-radius: 999px;
  background: var(--genai-accent);
  color: #ffffff;
  font-size: var(--genai-font-caption);
  font-weight: 700;
}}
.genai-guardrail-node-body {{ min-width: 0; overflow-wrap: anywhere; }}
.genai-guardrail-node-body .genai-card {{ margin-top: 0.4rem; }}
.genai-table-scroll {{ overflow-x: auto; }}
.genai-decision-table {{
  width: 100%;
  min-width: 52rem;
  border-collapse: collapse;
  font-size: var(--genai-font-caption);
}}
.genai-decision-table th, .genai-decision-table td {{
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--genai-border);
  text-align: left;
  vertical-align: top;
}}
.genai-decision-table th {{ color: var(--genai-muted); font-weight: 600; }}
.genai-raw-record summary {{ cursor: pointer; color: var(--genai-accent); }}
.genai-raw-record pre {{
  max-height: 14rem;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: var(--genai-font-caption);
}}
.genai-evidence-chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: var(--genai-gap);
}}
.genai-chip-link {{
  color: inherit;
  text-decoration: none;
  overflow-wrap: anywhere;
}}
.genai-chip-link:hover, .genai-chip-link:focus-visible {{ text-decoration: underline; }}
.genai-decision-history details {{
  border: 1px solid var(--genai-border);
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.5rem;
  background: var(--genai-surface);
}}
.genai-decision-history summary {{ cursor: pointer; color: var(--genai-accent); }}
.genai-audit-timeline {{ overflow-x: auto; }}
.genai-audit-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: var(--genai-font-caption);
}}
.genai-audit-table th, .genai-audit-table td {{
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--genai-border);
  text-align: left;
  vertical-align: top;
}}
.genai-audit-table th {{ color: var(--genai-muted); font-weight: 600; }}
.genai-audit-time, .genai-audit-request {{ white-space: nowrap; }}
.genai-audit-detail {{ min-width: 12rem; }}
.genai-audit-detail summary {{ cursor: pointer; color: var(--genai-accent); }}
.genai-audit-detail pre {{
  max-height: 12rem;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: var(--genai-font-caption);
}}
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
  .genai-app-header {{ align-items: flex-start; flex-direction: column; }}
}}
@media (max-width: 640px) {{
  .stApp .block-container {{ padding-left: 0.5rem; padding-right: 0.5rem; }}
  .genai-header-chips {{ flex-wrap: wrap; }}
  .stApp h1 {{ font-size: 1.5rem; }}
  .stApp h2 {{ font-size: 1.25rem; }}
  .stApp [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  .stApp .stDataFrame {{ overflow-x: auto; }}
  .genai-card {{ padding: 0.5rem; }}
  .genai-kpi-strip {{ grid-template-columns: 1fr; }}
  .genai-latency-row {{ flex-wrap: wrap; }}
  .genai-latency-label, .genai-latency-value {{ min-width: 100%; text-align: left; }}
  .genai-score-track {{ width: 100%; }}
  .genai-compare-table, .genai-waterfall-table, .genai-diff-table {{ font-size: var(--genai-font-caption); }}
  .genai-waterfall-track {{ min-width: 3rem; width: 100%; }}
  .genai-cost-row, .genai-failure-row, .genai-guardrail-row {{ grid-template-columns: 1fr; gap: 0.2rem; }}
  .genai-cost-value, .genai-failure-value, .genai-guardrail-value {{ min-width: 0; text-align: left; }}
  .genai-diff-cards {{ grid-template-columns: 1fr; }}
  .genai-guardrail-chain {{ grid-template-columns: 1fr; }}
  .genai-guardrail-node {{ display: flex; width: 100%; }}
  .genai-guardrail-node + .genai-guardrail-arrow {{ padding: 0.25rem 0; }}
  .genai-decision-table {{ min-width: 44rem; }}
  .genai-audit-table {{ min-width: 52rem; }}
  .genai-evidence-chips {{ flex-direction: column; align-items: flex-start; }}
  .genai-evidence-chips .genai-chip {{ max-width: 100%; }}
}}
</style>
"""
