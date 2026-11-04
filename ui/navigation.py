"""Console information architecture and role-aware navigation (issue #130).

This module is intentionally free of Streamlit and backend imports so the
navigation contract (groups, role landing, capability filtering, quick actions
and the onboarding checklist) can be unit-tested without a browser or a running
API.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

ALL_CAPABILITIES = (
    "query",
    "batch",
    "evaluate",
    "experiment",
    "rebuild",
    "introspect",
    "governance",
    "audit",
    "admin",
)


@dataclass(frozen=True)
class NavGroup:
    """A labelled, ordered group of screens in the sidebar."""

    key: str
    label: str
    description: str
    screens: Tuple[str, ...]


NAV_GROUPS: Tuple[NavGroup, ...] = (
    NavGroup(
        key="start",
        label="Start here",
        description="Service health, onboarding and the query workflow.",
        screens=("Overview / Health", "Query Studio"),
    ),
    NavGroup(
        key="experiment",
        label="Experiment",
        description="Score answers and compare retrieval strategies.",
        screens=("Evaluation", "Compare (what-if)"),
    ),
    NavGroup(
        key="governance",
        label="Governance & security",
        description="Cost, guardrails, audit evidence and access policy.",
        screens=("Governance & Cost", "Guardrails", "Audit", "Access / RBAC"),
    ),
    NavGroup(
        key="operate",
        label="Operate",
        description="Inspect traces, tenants and the runtime pipeline.",
        screens=("Traces", "Admin"),
    ),
    NavGroup(
        key="reference",
        label="Reference",
        description="Read-only configuration and provider listings.",
        screens=("Settings (read-only)",),
    ),
)

SCREEN_CAPABILITIES: Dict[str, Optional[str]] = {
    "Overview / Health": None,
    "Query Studio": "query",
    "Compare (what-if)": "rebuild",
    "Evaluation": "evaluate",
    "Governance & Cost": "governance",
    "Guardrails": "introspect",
    "Audit": "audit",
    "Access / RBAC": "introspect",
    "Admin": "rebuild",
    "Traces": "governance",
    "Settings (read-only)": "introspect",
}


@dataclass(frozen=True)
class QuickAction:
    label: str
    screen: str
    capability: Optional[str]
    help: str


QUICK_ACTIONS: Tuple[QuickAction, ...] = (
    QuickAction(
        label="Run a query",
        screen="Query Studio",
        capability="query",
        help="Ask a question and inspect documents, cost and latency.",
    ),
    QuickAction(
        label="Look up the last trace",
        screen="Traces",
        capability="governance",
        help="Open the redacted trace for the most recent request.",
    ),
    QuickAction(
        label="Evaluate a response",
        screen="Evaluation",
        capability="evaluate",
        help="Score a response with the active or a named evaluator.",
    ),
    QuickAction(
        label="Review governance",
        screen="Governance & Cost",
        capability="governance",
        help="Check spend, failures and guardrail decisions.",
    ),
)


@dataclass(frozen=True)
class ChecklistStep:
    key: str
    label: str
    detail: str
    screen: Optional[str]


CHECKLIST_STEPS: Tuple[ChecklistStep, ...] = (
    ChecklistStep(
        key="backend",
        label="Connect to the backend",
        detail="Health and readiness answer at the configured API base URL.",
        screen=None,
    ),
    ChecklistStep(
        key="query",
        label="Run your first query",
        detail="Ask a question and inspect documents, cost and latency.",
        screen="Query Studio",
    ),
    ChecklistStep(
        key="trace",
        label="Inspect the trace",
        detail="Open the redacted trace for the request you just ran.",
        screen="Traces",
    ),
    ChecklistStep(
        key="evaluate",
        label="Score a response",
        detail="Run the semantic or LLM-judge evaluator against an answer.",
        screen="Evaluation",
    ),
    ChecklistStep(
        key="governance",
        label="Review governance",
        detail="Check spend, failures and guardrail decisions.",
        screen="Governance & Cost",
    ),
)


def effective_capabilities(enabled: bool, configured: Iterable[str]) -> List[str]:
    """Return the capabilities the console may use.

    When RBAC is disabled every capability is available (the legacy default).
    When it is enabled, only what the backend reported is granted.
    """
    if not enabled:
        return list(ALL_CAPABILITIES)
    return [capability for capability in configured if capability]


def can_access(screen: str, capabilities: Iterable[str]) -> bool:
    """Whether the capabilities allow opening ``screen``."""
    required = SCREEN_CAPABILITIES.get(screen)
    if required is None:
        return screen in SCREEN_CAPABILITIES
    return required in set(capabilities)


def visible_screens(
    screens: Iterable[str], capabilities: Iterable[str], show_all: bool = False
) -> List[str]:
    """Filter ``screens`` by capability (or return all when ``show_all``)."""
    ordered = list(screens)
    if show_all:
        return ordered
    granted = set(capabilities)
    return [screen for screen in ordered if can_access(screen, granted)]


def grouped_screens(
    screens: Iterable[str], capabilities: Iterable[str], show_all: bool = False
) -> List[NavGroup]:
    """Return navigation groups filtered to the visible screens."""
    ordered = list(screens)
    visible = set(visible_screens(ordered, capabilities, show_all=show_all))
    groups: List[NavGroup] = []
    for group in NAV_GROUPS:
        members = tuple(screen for screen in group.screens if screen in visible and screen in ordered)
        if members:
            groups.append(
                NavGroup(
                    key=group.key,
                    label=group.label,
                    description=group.description,
                    screens=members,
                )
            )
    return groups


def hidden_screens(
    screens: Iterable[str], capabilities: Iterable[str], show_all: bool = False
) -> List[str]:
    """Return screens omitted because the role lacks the capability."""
    ordered = list(screens)
    visible = set(visible_screens(ordered, capabilities, show_all=show_all))
    return [screen for screen in ordered if screen not in visible]


def landing_screen(role: str, capabilities: Iterable[str], screens: Iterable[str]) -> str:
    """Choose the default screen for a role, falling back to Overview."""
    ordered = list(screens)
    granted = set(capabilities)
    lowered = (role or "").lower()

    candidate = "Overview / Health"
    if "audit" in lowered:
        candidate = "Audit"
    elif any(token in lowered for token in ("security", "compliance", "risk")):
        candidate = "Guardrails"
    elif any(token in lowered for token in ("ops", "sre", "platform", "finops")):
        candidate = "Governance & Cost"
    elif any(token in lowered for token in ("analyst", "evaluat", "data", "ml")):
        candidate = "Evaluation"
    elif "admin" in lowered:
        candidate = "Overview / Health"
    elif "audit" in granted and "query" not in granted:
        candidate = "Audit"
    elif "query" in granted:
        candidate = "Query Studio"

    if candidate in ordered and can_access(candidate, granted):
        return candidate
    if "Overview / Health" in ordered and can_access("Overview / Health", granted):
        return "Overview / Health"
    return ordered[0] if ordered else "Overview / Health"


def quick_actions_for(capabilities: Iterable[str]) -> List[QuickAction]:
    """Quick actions the role is allowed to run, in declaration order."""
    granted = set(capabilities)
    return [
        action
        for action in QUICK_ACTIONS
        if action.capability is None or action.capability in granted
    ]


def checklist_status(done: Mapping[str, bool]) -> List[Tuple[ChecklistStep, bool]]:
    """Pair each onboarding step with its completion flag."""
    return [(step, bool(done.get(step.key))) for step in CHECKLIST_STEPS]


def role_label(role: str) -> str:
    """Human-friendly role name (``platform-ops`` -> ``Platform Ops``)."""
    cleaned = (role or "").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "Unknown"
