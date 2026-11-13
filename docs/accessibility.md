# Console accessibility decision record (issue #155)

Status: accepted 2026-11-12. Applies to the Streamlit console (`ui/`).

The console is an HTTP-only reference front-end; accessibility expectations are
therefore scoped to the screens shipped in `ui/app.py` and the interactions the
app owns (navigation, dialogs, forms, tables, downloads). Streamlit owns the DOM
shell, theme and third-party grid, so a small number of platform constraints are
recorded as known exceptions rather than silently ignored.

## 1. Decision

- Ship a **command palette** (`ui/palette.py`) as the keyboard-first launcher for
  screens, quick actions, recent request ids and tenants, with predictable
  prefixes: `/` screen, `>` action, `#` request id, `@` tenant.
- Ship a discoverable **help overlay** listing the keyboard map, the WCAG 2.2 AA
  checklist and the known exceptions.
- Inject a small stylesheet (`ui/a11y.py`) that adds a skip link, a global
  `:focus-visible` ring, screen-reader-only text and a
  `prefers-reduced-motion` reset.
- Keep the palette and checklist **pure modules** so logic and wording can be
  tested without Streamlit, and keep the HTTP-only rule intact.

## 2. Keyboard map

| Action | Keys | Scope |
| --- | --- | --- |
| Open the command palette | `Ctrl+K` / `Cmd+K`, or the sidebar button | Global |
| Open the palette without a mouse | `?palette=1` deep link, then Tab | Global |
| Run the palette search | `Enter` | Command palette |
| Move through results | `Tab` / `Shift+Tab` | Command palette |
| Open the highlighted result | `Enter` / `Space` | Command palette |
| Keyboard shortcuts and accessibility | palette search `shortcuts` | Global |
| Skip to main content | `Tab`, then `Enter` on the skip link | Global |
| Close a dialog | `Esc` or the close button | Dialogs |
| Submit the query form | `Enter` in a field or activate Submit | Query Studio |

Streamlit cannot bind global browser shortcuts without a custom component, so
`Ctrl/Cmd+K` is documented and the palette remains fully reachable and
operable from the keyboard (sidebar button or `?palette=1`). This is the only
intentional deviation from the issue text and is repeated in the in-app help.

## 3. Implementation notes

- `ui/palette.py`: `parse_query`, `build_items`, `filter_items`,
  `resolve_action`, `SHORTCUTS`, `shortcut_help_markdown`. Capability filtering
  reuses `ui/navigation.py`, so the palette never offers a screen the caller
  cannot open.
- `ui/a11y.py`: `A11Y_CSS`, `skip_link_html`, `sr_only`, `WCAG_CHECKLIST`,
  `KNOWN_EXCEPTIONS`, `SCREEN_READER_SCRIPT`, `checklist_summary`.
- `ui/app.py`: styles and skip link render first; `_palette_dialog` is a
  Streamlit form (Tab/Enter), `_shortcuts_dialog` renders the checklist,
  `Admin` records known tenants so `@tenant` searches work.
- Focus after navigation: palette selections navigate through session state and
  rerun, so Streamlit restores the sidebar/controls in document order; the
  skip-link target (`#genai-main-content`) is the first anchor in the main area.

## 4. Reduced motion and contrast

- `@media (prefers-reduced-motion: reduce)` collapses animation, transition and
  smooth-scroll durations to near zero for every element.
- Focus rings use `#0b5fff` at 3px with a 2px offset, meeting 3:1 non-text
  contrast on the default light theme; custom skip-link text uses `#0b3d91` on
  white (>4.5:1).
- Wide tables scroll inside their container so the page does not require
  horizontal scrolling at 200% zoom.

## 5. WCAG 2.2 AA checklist

| Criterion | Level | Status | Note |
| --- | --- | --- | --- |
| 1.3.1 Info and Relationships | A | meets | Grouped navigation, labelled inputs, captions and headings. |
| 1.4.3 Contrast (Minimum) | AA | meets | Default theme plus custom focus/skip colours verified. |
| 1.4.4 Resize Text | AA | meets | Browser zoom to 200% verified manually. |
| 1.4.10 Reflow | AA | meets | Tables scroll locally; no page-level horizontal scroll. |
| 1.4.11 Non-text Contrast | AA | meets | 3px `#0b5fff` focus ring. |
| 2.1.1 Keyboard | A | meets | Palette is a form; all actions have a keyboard path. |
| 2.1.2 No Keyboard Trap | A | meets | Dialogs close with Esc/close; rerun restores focus order. |
| 2.4.1 Bypass Blocks | A | meets | Skip link is the first focusable element. |
| 2.4.3 Focus Order | A | meets | Sidebar, workspace controls, then screen content. |
| 2.4.7 Focus Visible | AA | meets | Global `:focus-visible` outline. |
| 2.4.11 Focus Not Obscured | AA | meets | Sticky sidebar/dialogs keep the control in view. |
| 2.5.7 Dragging Movements | AA | meets | Data editors have add/move/delete buttons. |
| 2.5.8 Target Size | AA | meets | Full-width nav targets and standard buttons. |
| 3.2.6 Consistent Help | A | meets | Help, tour and shortcuts stay in the sidebar. |
| 3.3.7 Redundant Entry | A | meets | Workspace state and recent runs avoid retyping. |
| 4.1.2 Name, Role, Value | A | meets | Native control names; palette results are buttons. |

## 6. Known exceptions

- **Ctrl/Cmd+K interception**: no global key binding without a custom component;
  documented, with keyboard-reachable alternatives.
- **Live-region announcements**: Streamlit owns the DOM; status uses
  `st.success`/`st.warning`, announced on the next navigation.
- **Third-party dataframe grid**: exact values needed for evidence/audit are
  duplicated in captions and JSON expanders.

## 7. Screen-reader test script

1. Start NVDA (Windows) or VoiceOver (macOS) and open the console at the
   configured API base URL.
2. Tab once: "Skip to main content" is announced; press Enter and confirm focus
   lands on the main heading.
3. Tab to the sidebar: each nav group expands, the active screen is announced as
   the primary control.
4. Open "Command palette" from the sidebar; type `trace`; confirm results
   announce label, kind and category.
5. Tab to the first result, Enter, and confirm Traces opens with the request id
   populated.
6. Run a query; confirm the answer, cost and latency are announced in reading
   order.
7. Open "Keyboard shortcuts and accessibility" from the palette; confirm the
   dialog is announced, Esc closes it and focus returns.
8. Zoom to 200% and repeat steps 2-6; no page-level horizontal scrolling.
9. Enable "Reduce motion" in the OS and confirm dialogs/progress do not animate.
10. Record failures in this decision record before release.

## 8. Verification

- `tests/test_ui_palette.py`: parsing/ranking/actions, shortcut registration,
  checklist contract, AST wiring, pure-module guards.
- Existing console guards (`tests/test_ui_console.py`, `tests/test_ux_navigation.py`,
  `tests/test_ui_new_features.py`) continue to run, including the HTTP-only scan.
- Manual: keyboard-only pass of Overview, Query Studio, Traces, Governance,
  Approvals, Audit and Admin at 100% and 200% zoom, light theme.
