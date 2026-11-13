"""Command palette contract and keyboard shortcuts (issue #155).

The palette is a keyboard-first entry point for the console: screens, quick
actions, recent request ids and tenant filters can all be reached from one
search box. The parsing, ranking and navigation contract lives here so it can
be tested without Streamlit or a running API.

Prefixes keep the search predictable::

    / screen    > action    # request id    @ tenant

Anything without a prefix searches every kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ui.navigation import (
    NAV_GROUPS,
    can_access,
    quick_actions_for,
)

MAX_RESULTS = 12
MAX_RECENT_REQUESTS = 8
MAX_TENANTS = 8
HELP_TARGET = "keyboard-shortcuts"

KIND_ORDER: Dict[str, int] = {
    "screen": 0,
    "action": 1,
    "request": 2,
    "tenant": 3,
    "help": 4,
}

PREFIX_KINDS: Dict[str, str] = {
    "/": "screen",
    ">": "action",
    "#": "request",
    "@": "tenant",
}

KIND_LABELS: Dict[str, str] = {
    "screen": "Screen",
    "action": "Action",
    "request": "Request id",
    "tenant": "Tenant",
    "help": "Help",
}


@dataclass(frozen=True)
class PaletteItem:
    """One selectable palette result."""

    id: str
    label: str
    kind: str
    target: str
    category: str
    keywords: str = ""
    help: str = ""


@dataclass(frozen=True)
class PaletteQuery:
    """A parsed palette search box value."""

    raw: str
    kind: Optional[str]
    needle: str


@dataclass(frozen=True)
class Shortcut:
    """A documented keyboard interaction."""

    action: str
    keys: str
    scope: str


SHORTCUTS: Tuple[Shortcut, ...] = (
    Shortcut(
        action="Open the command palette",
        keys="Ctrl+K / Cmd+K, or the Command palette button in the sidebar",
        scope="Global",
    ),
    Shortcut(
        action="Run the palette search",
        keys="Enter",
        scope="Command palette",
    ),
    Shortcut(
        action="Move through results",
        keys="Tab / Shift+Tab",
        scope="Command palette",
    ),
    Shortcut(
        action="Open the highlighted result",
        keys="Enter / Space",
        scope="Command palette",
    ),
    Shortcut(
        action="Show keyboard shortcuts and accessibility notes",
        keys="Search for 'shortcuts' in the palette",
        scope="Global",
    ),
    Shortcut(
        action="Skip the sidebar and go to main content",
        keys="Tab then Enter on 'Skip to main content'",
        scope="Global",
    ),
    Shortcut(
        action="Close a dialog",
        keys="Esc or the dialog close button",
        scope="Dialogs",
    ),
    Shortcut(
        action="Run the query form",
        keys="Enter inside a text field, or activate Submit",
        scope="Query Studio",
    ),
)


def parse_query(text: Optional[str]) -> PaletteQuery:
    """Split an optional kind prefix from the search needle."""
    raw = (text or "").strip()
    if not raw:
        return PaletteQuery(raw=raw, kind=None, needle="")
    prefix = raw[0]
    kind = PREFIX_KINDS.get(prefix)
    if kind is None:
        return PaletteQuery(raw=raw, kind=None, needle=raw.lower())
    return PaletteQuery(raw=raw, kind=kind, needle=raw[1:].strip().lower())


def _dedupe(values: Iterable[Any], limit: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def recent_request_ids(
    entries: Iterable[Mapping[str, Any]],
    limit: int = MAX_RECENT_REQUESTS,
) -> List[str]:
    """Request ids from the query history, newest first."""
    return _dedupe(
        [(entry or {}).get("request_id") for entry in entries or []], limit
    )


def _group_for(screen: str) -> str:
    for group in NAV_GROUPS:
        if screen in group.screens:
            return group.label
    return "Screens"


def build_items(
    screens: Sequence[str],
    capabilities: Iterable[str],
    recent_requests: Sequence[str] = (),
    tenants: Sequence[str] = (),
) -> List[PaletteItem]:
    """Build the palette catalogue for the caller's capabilities."""
    granted = list(capabilities)
    items: List[PaletteItem] = []

    for screen in screens:
        if not can_access(screen, granted):
            continue
        group = _group_for(screen)
        items.append(
            PaletteItem(
                id=f"screen::{screen}",
                label=screen,
                kind="screen",
                target=screen,
                category=group,
                keywords=f"{group} screen open go navigate",
                help=f"Open the {screen} screen",
            )
        )

    for action in quick_actions_for(granted):
        items.append(
            PaletteItem(
                id=f"action::{action.label}",
                label=action.label,
                kind="action",
                target=action.screen,
                category="Quick actions",
                keywords=f"quick action {action.help}",
                help=action.help,
            )
        )

    for request_id in _dedupe(recent_requests, MAX_RECENT_REQUESTS):
        items.append(
            PaletteItem(
                id=f"request::{request_id}",
                label=f"Trace {request_id}",
                kind="request",
                target=request_id,
                category="Recent requests",
                keywords=f"request trace evidence {request_id}",
                help=f"Open the trace for request {request_id}",
            )
        )

    for tenant in _dedupe(tenants, MAX_TENANTS):
        items.append(
            PaletteItem(
                id=f"tenant::{tenant}",
                label=f"Tenant {tenant}",
                kind="tenant",
                target=tenant,
                category="Tenants",
                keywords=f"tenant filter governance spend {tenant}",
                help=f"Filter governance and cost by tenant {tenant}",
            )
        )

    items.append(
        PaletteItem(
            id="help::shortcuts",
            label="Keyboard shortcuts and accessibility",
            kind="help",
            target=HELP_TARGET,
            category="Help",
            keywords="accessibility a11y wcag screen reader shortcuts keys help",
            help="Show the keyboard map, WCAG 2.2 AA checklist and known exceptions",
        )
    )
    return items


def _subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    remaining = iter(haystack)
    return all(char in remaining for char in needle)


def _score(item: PaletteItem, needle: str) -> Optional[int]:
    if not needle:
        return 0
    label = item.label.lower()
    haystack = f"{label} {item.keywords.lower()} {item.category.lower()}"
    if label == needle:
        return 0
    if label.startswith(needle):
        return 1
    if any(token.startswith(needle) for token in haystack.replace("/", " ").split()):
        return 2
    if needle in label:
        return 3
    if needle in haystack:
        return 4
    if _subsequence(needle, label):
        return 5
    return None


def filter_items(
    items: Iterable[PaletteItem],
    query: Any,
    limit: int = MAX_RESULTS,
) -> List[PaletteItem]:
    """Rank items for a query, honouring the kind prefix and a result cap."""
    parsed = query if isinstance(query, PaletteQuery) else parse_query(str(query))
    scored: List[Tuple[int, int, str, PaletteItem]] = []
    for item in items:
        if parsed.kind is not None and item.kind != parsed.kind:
            continue
        score = _score(item, parsed.needle)
        if score is None:
            continue
        scored.append((score, KIND_ORDER.get(item.kind, 99), item.label.lower(), item))
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in scored[: max(1, limit)]]


def resolve_action(item: PaletteItem) -> Dict[str, Any]:
    """Translate a palette selection into console navigation state."""
    if item.kind == "help":
        return {"help": True}
    if item.kind == "request":
        return {"screen": "Traces", "request_id": item.target}
    if item.kind == "tenant":
        return {"screen": "Governance & Cost", "tenant": item.target}
    return {"screen": item.target}


def shortcut_rows() -> List[Dict[str, str]]:
    """Table rows for the in-app shortcut help overlay."""
    return [
        {"action": shortcut.action, "keys": shortcut.keys, "scope": shortcut.scope}
        for shortcut in SHORTCUTS
    ]


def shortcut_help_markdown() -> str:
    """Markdown used by the help dialog and documentation."""
    lines = ["### Keyboard and accessibility", "", "| Action | Keys | Scope |", "| --- | --- | --- |"]
    for shortcut in SHORTCUTS:
        lines.append(f"| {shortcut.action} | {shortcut.keys} | {shortcut.scope} |")
    return "\n".join(lines)
