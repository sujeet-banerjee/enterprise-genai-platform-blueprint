# Console layout and theme tokens (issue #156)

The Streamlit console (`ui/`) ships a small, testable appearance layer in
`ui/theme.py`. It is pure Python: no Streamlit or backend imports. `ui/app.py`
injects the generated CSS and renders the controls; every other screen inherits
the tokens.

## Layout breakpoints

| Name | Width | Behaviour |
| --- | --- | --- |
| `compact` | 0-639 px | Single column, reduced page padding, smaller headings, horizontal table scroll, stacked card fields. |
| `tablet` | 640-1023 px | Reduced page padding, card fields stack, sidebar collapses by default (`initial_sidebar_state="auto"`). |
| `desktop` | 1024-1439 px | Full layout; sidebar becomes sticky so primary actions stay visible while scrolling. |
| `wide` | 1440 px and up | Same as desktop with the full `layout="wide"` canvas. |

The documented verification widths are **375 px**, **768 px** and **1280 px**.
No screen should require horizontal scrolling at those widths; tables that
cannot fit degrade to cards with every column and action preserved.

## Themes

| Theme | Background | Surface | Text | Accent |
| --- | --- | --- | --- | --- |
| `Light` | `#ffffff` | `#f6f8fa` | `#1f2328` | `#0b5fff` |
| `Dark` | `#0d1117` | `#161b22` | `#e6edf3` | `#4493f8` |
| `High contrast` | `#000000` | `#000000` | `#ffffff` | `#ffff00` |

Every text, muted, accent, success, warning and danger token meets **WCAG 2.2 AA
(4.5:1)** against its theme background; chart colours meet at least 3:1.
`theme.theme_contrast_rows()` returns the evidence and the test suite asserts it.

## Density

| Density | Row height | Padding | Gap | Font size |
| --- | --- | --- | --- | --- |
| `Comfortable` | `2.25rem` | `1rem` | `1rem` | `1rem` |
| `Compact` | `1.75rem` | `0.5rem` | `0.5rem` | `0.9rem` |

Compact mode reduces vertical rhythm for operational screens; it never hides
values or actions.

## Table-to-card degradation

`theme.table_to_cards(rows, columns, title_columns)` converts any table to cards:

- the card title comes from the first non-empty `title_columns` value (default:
  the first column) and falls back to `Item`;
- **every** column is emitted as a `{label, value}` field, including action
  columns, so no control disappears when a table becomes cards;
- `None` renders as `-`, booleans as `yes`/`no`, everything else as text;
- cards use the `.genai-card` CSS class (surface, border, responsive grid).

The Guardrails screen (resolved chains, per-request decisions, hit-rate table)
is the first consumer; the same helper is available to any screen.

## CSS tokens

`theme.styles(theme, density)` exposes these custom properties on `:root`:

`--genai-bg`, `--genai-surface`, `--genai-text`, `--genai-muted`,
`--genai-border`, `--genai-accent`, `--genai-accent-text`, `--genai-focus`,
`--genai-success`, `--genai-warning`, `--genai-danger`, `--genai-chart`,
`--genai-gap`, `--genai-padding`, `--genai-row-height`, `--genai-font-size`,
`--genai-line-height`.

Focus rings, reduced motion and the skip link come from `ui/a11y.py` (UX12);
theme and density only add colour, spacing and responsive rules, so the two
layers never conflict.

## Switching without losing work

Theme, density and table layout live in session state (`ui_theme`,
`ui_density`, `ui_table_layout`). Changing them re-runs Streamlit but keeps the
active screen, query text, workspace, and saved views, because those are already
stored in session state. Appearance is deliberately not written to share URLs;
workspace links stay focused on analytical state.
