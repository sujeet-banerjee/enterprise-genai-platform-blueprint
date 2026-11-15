"""Role-based guided journeys and safe demo mode (issue #157).

Pure helpers: role-to-journey mapping, journey progress, the demo seed/reset
contract and the local demo fixtures. The module deliberately avoids Streamlit
and backend imports so the journey and demo contracts can be unit-tested without
a browser or a live API.

Demo mode is a *local* simulation: ``ui.demo.DemoApi`` serves these fixtures and
never issues HTTP requests, so demo mode cannot read or write production tenant
data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ui.query_studio import build_history_entry
from ui.workspace import reset_workspace_state

DEMO_REQUEST_ID = "demo-request-0001"
DEMO_QUERY = "What is retrieval augmented generation?"
DEMO_TIMESTAMP = "2026-11-13T09:00:00+00:00"
DEMO_EPOCH = 1763024400.0

DOC_BASE_URL = (
    "https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/"
)


@dataclass(frozen=True)
class JourneyStep:
    """One screen in a role journey with its goal and matching documentation."""

    title: str
    screen: str
    goal: str
    doc: str
    try_it: str


@dataclass(frozen=True)
class RoleJourney:
    """A short, ordered path through the console for one persona."""

    key: str
    label: str
    audience: str
    description: str
    steps: Tuple[JourneyStep, ...]

    @property
    def screens(self) -> List[str]:
        return [step.screen for step in self.steps]


ROLE_JOURNEYS: Dict[str, RoleJourney] = {
    "architect": RoleJourney(
        key="architect",
        label="Architect",
        audience="Solution and enterprise architects",
        description=(
            "Understand the config-driven topology, swap components safely and see "
            "how evaluation and governance bound the design."
        ),
        steps=(
            JourneyStep(
                title="Read the live topology",
                screen="Overview / Health",
                goal="Confirm health, readiness and the active model/retriever/evaluator.",
                doc="docs/architecture.md",
                try_it="Compare the tiles with the config-driven registry list.",
            ),
            JourneyStep(
                title="Inspect the effective configuration",
                screen="Settings (read-only)",
                goal="See the redacted config and provider registries behind the topology.",
                doc="docs/architecture.md#121-config-schemas-validation-and-secrets-issue-46",
                try_it="Confirm secrets are shown as [REDACTED].",
            ),
            JourneyStep(
                title="Swap a component",
                screen="Compare (what-if)",
                goal="Rebuild the pipeline with a different retriever or similarity metric.",
                doc="docs/architecture.md#9-observability-and-operations",
                try_it="Apply a what-if, then run the same query to compare.",
            ),
            JourneyStep(
                title="Quantify quality",
                screen="Evaluation",
                goal="Score answers and compare embedding/chunking strategies.",
                doc="docs/ux-and-api.md#6-console-page-map",
                try_it="Run a small dataset evaluation and inspect the metric matrix.",
            ),
        ),
    ),
    "analyst": RoleJourney(
        key="analyst",
        label="Analyst",
        audience="Data, ML and evaluation analysts",
        description=(
            "Run questions, inspect grounding evidence, build datasets and compare "
            "quality over time."
        ),
        steps=(
            JourneyStep(
                title="Run a first query",
                screen="Query Studio",
                goal="Ask a question and inspect the answer, documents, cost and latency.",
                doc="docs/ux-and-api.md",
                try_it="Apply the RAG basics template and run it.",
            ),
            JourneyStep(
                title="Check the evidence",
                screen="Traces",
                goal="Open the redacted trace and see which documents grounded the answer.",
                doc="docs/architecture.md#9-observability-and-operations",
                try_it="Open the trace for the request you just ran.",
            ),
            JourneyStep(
                title="Build an evaluation dataset",
                screen="Evaluation",
                goal="Author cases with references and tags in the Dataset Studio.",
                doc="docs/analysis/ux_roadmap_fact_check.md",
                try_it="Add a case with a reference answer, save it and start a job.",
            ),
            JourneyStep(
                title="Compare runs",
                screen="Query Studio",
                goal="Use history and Compare with last run to spot regressions.",
                doc="docs/ux-and-api.md#6-console-page-map",
                try_it="Run the same query twice and inspect the delta table.",
            ),
        ),
    ),
    "security": RoleJourney(
        key="security",
        label="Security / compliance",
        audience="Security, risk and compliance reviewers",
        description=(
            "Verify guardrails, audit evidence, access scope and human-in-the-loop "
            "controls before approving a rollout."
        ),
        steps=(
            JourneyStep(
                title="Review guardrails",
                screen="Guardrails",
                goal="Confirm the resolved input/output chains, profile and hit rate.",
                doc="docs/architecture.md#8-guardrails-and-safety",
                try_it="Run the injection probe and confirm the block decision.",
            ),
            JourneyStep(
                title="Read the audit trail",
                screen="Audit",
                goal="Inspect append-only, redacted events for queries and rebuilds.",
                doc="docs/architecture.md#95-audit-trail",
                try_it="Filter by request id and jump to the matching trace.",
            ),
            JourneyStep(
                title="Review approvals",
                screen="Approvals",
                goal="Approve or reject policy-gated actions with a reviewer note.",
                doc="docs/ux-and-api.md#6-console-page-map",
                try_it="Inspect a pending request and submit a decision.",
            ),
            JourneyStep(
                title="Check access scope",
                screen="Access / RBAC",
                goal="Verify the role, effective capabilities and tenant scope.",
                doc="docs/deployment.md#121-config-schemas-validation-and-secrets-issue-46",
                try_it="Compare capabilities with and without the API key.",
            ),
        ),
    ),
    "ops": RoleJourney(
        key="ops",
        label="Platform ops",
        audience="SRE, platform and FinOps operators",
        description=(
            "Watch cost, failures and latency, follow traces, and verify deployment "
            "and tenant controls."
        ),
        steps=(
            JourneyStep(
                title="Watch governance and spend",
                screen="Governance & Cost",
                goal="Check the cost cap, spend window, failure rate and guardrail hit rate.",
                doc="docs/architecture.md#9-observability-and-operations",
                try_it="Run a few queries and watch the rolling metrics change.",
            ),
            JourneyStep(
                title="Follow a slow request",
                screen="Traces",
                goal="Use the per-stage latency table, resilience block and OTel ids.",
                doc="docs/deployment.md#9-observability",
                try_it="Compare two requests to see which stage moved.",
            ),
            JourneyStep(
                title="Check tenant controls",
                screen="Admin",
                goal="List tenants/users and review budget proposals.",
                doc="docs/deployment.md#13-deployment-modes",
                try_it="List tenants if your role has admin capability.",
            ),
            JourneyStep(
                title="Confirm the runtime contract",
                screen="Settings (read-only)",
                goal="Verify the effective config, models and guardrail providers.",
                doc="docs/deployment.md",
                try_it="Confirm no secrets are shown.",
            ),
        ),
    ),
    "admin": RoleJourney(
        key="admin",
        label="Administrator",
        audience="Tenant and platform administrators",
        description=(
            "Set up tenants and access, review policy and budgets, and confirm the "
            "runtime before onboarding a team."
        ),
        steps=(
            JourneyStep(
                title="Review the console baseline",
                screen="Overview / Health",
                goal="Confirm the backend, config revision and active components.",
                doc="docs/onboarding.md",
                try_it="Read the readiness revision and component tiles.",
            ),
            JourneyStep(
                title="Manage tenants and users",
                screen="Admin",
                goal="List tenants/users and propose budget updates.",
                doc="docs/deployment.md#13-deployment-modes",
                try_it="Open the tenant list and a budget proposal.",
            ),
            JourneyStep(
                title="Verify access policy",
                screen="Access / RBAC",
                goal="Check the calling role and effective capabilities.",
                doc="docs/architecture.md#14-multi-tenancy-and-attribution",
                try_it="Compare capabilities across API keys.",
            ),
            JourneyStep(
                title="Confirm guardrails and audit",
                screen="Guardrails",
                goal="Adopt a profile, then verify decisions and the audit trail.",
                doc="docs/architecture.md#8-guardrails-and-safety",
                try_it="Preview the standard profile and inspect a decision.",
            ),
            JourneyStep(
                title="Check spend controls",
                screen="Governance & Cost",
                goal="Confirm the cost cap, spend window and tenant attribution.",
                doc="docs/deployment.md#13-deployment-modes",
                try_it="Filter governance by tenant and app.",
            ),
        ),
    ),
}

JOURNEY_ORDER: Tuple[str, ...] = ("architect", "analyst", "security", "ops", "admin")

ROLE_TOKENS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("security", ("security", "compliance", "risk", "audit")),
    ("analyst", ("analyst", "evaluat", "data", "ml", "scientist")),
    ("admin", ("admin", "owner", "tenant-admin")),
    ("ops", ("ops", "sre", "platform", "finops", "operations", "reliability")),
    ("architect", ("architect", "solution", "enterprise")),
)

DEMO_WARNING = (
    "Demo mode is a local simulation: the console serves built-in fixtures and makes "
    "no backend requests, so no production tenant data is read or written."
)

DEMO_ROLE = "architect"
DEMO_TENANT = "demo"
DEMO_WORKSPACE = "showcase"

DEMO_DOCUMENTS: List[Dict[str, Any]] = [
    {
        "content": (
            "Retrieval augmented generation (RAG) combines a retriever with a language "
            "model so answers are grounded in retrieved evidence."
        ),
        "metadata": {"doc_id": 0, "source": "demo-handbook"},
        "score": 0.92,
    },
    {
        "content": (
            "Guardrails validate inputs and outputs before they reach the model or the "
            "caller, and every decision is recorded in the trace."
        ),
        "metadata": {"doc_id": 1, "source": "demo-security"},
        "score": 0.84,
    },
]

DEMO_RESULT: Dict[str, Any] = {
    "request_id": DEMO_REQUEST_ID,
    "response": (
        "Retrieval augmented generation grounds an answer in documents retrieved for the "
        "question. The demo trace shows the retrieved evidence, cost and latency."
    ),
    "retrieved_docs_with_scores": DEMO_DOCUMENTS,
    "cost": {"estimated_cost_usd": 0.00042},
    "latency": {
        "embedding": 41.0,
        "embedding_ms": 41.0,
        "retrieval": 12.0,
        "retrieval_ms": 12.0,
        "reranking": 25.0,
        "reranking_ms": 25.0,
        "llm_generation": 700.0,
        "llm_generation_ms": 700.0,
        "evaluation": 64.0,
        "evaluation_ms": 64.0,
        "total_ms": 842.0,
    },
    "cache_hit": False,
    "failure_tags": [],
    "guardrail_decisions": [
        {
            "guardrail": "injection",
            "stage": "guardrail_input",
            "decision": "allow",
            "allowed": True,
            "reason": "",
            "labels": [],
        }
    ],
    "observability": {
        "request_id": DEMO_REQUEST_ID,
        "status": "success",
        "redaction_enabled": True,
        "guardrails_enabled": True,
        "guardrail_decisions": [
            {
                "guardrail": "injection",
                "stage": "guardrail_input",
                "decision": "allow",
                "allowed": True,
                "reason": "",
                "labels": [],
            }
        ],
        "expanded_queries": [DEMO_QUERY],
        "retrieved_documents": DEMO_DOCUMENTS,
        "latency": {
            "stages": {
                "embedding": {"ms": 41.0, "count": 1},
                "retrieval": {"ms": 12.0, "count": 1},
                "reranking": {"ms": 25.0, "count": 1},
                "llm_generation": {"ms": 700.0, "count": 1},
                "evaluation": {"ms": 64.0, "count": 1},
            },
            "total_ms": 842.0,
        },
        "resilience": {
            "served_by": "demo-llm",
            "attempts": 1,
            "retries": 0,
            "failovers": 0,
        },
        "otel": {"trace_id": "demo-trace-0001", "span_id": "demo-span-0001"},
    },
}

DEMO_DATASET: Dict[str, Any] = {
    "name": "Demo onboarding set",
    "docs": [
        {
            "title": "Demo handbook",
            "content": "Retrieval augmented generation grounds answers in retrieved evidence.",
        }
    ],
    "cases": [
        {
            "query": DEMO_QUERY,
            "reference": "RAG grounds answers in retrieved documents.",
            "tags": ["demo", "basics"],
        }
    ],
}

DEMO_SEED_KEYS: Tuple[str, ...] = (
    "demo_mode",
    "demo_role",
    "demo_started_at",
    "journey_state",
    "journey_role",
    "journey_step",
    "last_request_id",
    "last_query",
    "last_trace_request_id",
    "last_evaluation_at",
    "last_governance_seen",
    "last_guardrail_at",
    "last_audit_at",
    "last_admin_at",
    "query_history",
    "qs_last_entry",
    "qs_last_baseline",
    "saved_datasets",
    "workspace_scope",
    "checklist_hidden",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def journey_for_role(role: str) -> RoleJourney:
    """Map a free-form role label to one of the role journeys."""
    lowered = (role or "").strip().lower()
    for key, tokens in ROLE_TOKENS:
        if any(token in lowered for token in tokens):
            return ROLE_JOURNEYS[key]
    return ROLE_JOURNEYS[DEMO_ROLE]


def journey_by_key(key: str) -> RoleJourney:
    """Return a journey by key, falling back to the default role."""
    return ROLE_JOURNEYS.get((key or "").strip().lower(), ROLE_JOURNEYS[DEMO_ROLE])


def journey_labels() -> List[str]:
    return [ROLE_JOURNEYS[key].label for key in JOURNEY_ORDER]


def journey_key_for_label(label: str) -> str:
    for key in JOURNEY_ORDER:
        if ROLE_JOURNEYS[key].label.lower() == (label or "").strip().lower():
            return key
    return DEMO_ROLE


def journey_steps(key: str) -> List[JourneyStep]:
    return list(journey_by_key(key).steps)


def doc_url(doc: str) -> str:
    """Absolute URL for an in-repo documentation path (safe for Markdown links)."""
    path = str(doc or "").strip().lstrip("/")
    if not path:
        return ""
    return f"{DOC_BASE_URL}{path}"


def mark_screen_visited(visited: Sequence[str], screen: str) -> List[str]:
    """Return ``visited`` with ``screen`` appended once (order preserved)."""
    out = [str(item) for item in visited]
    name = str(screen or "").strip()
    if name and name not in out:
        out.append(name)
    return out


def journey_progress(key: str, completed: Mapping[str, bool]) -> Tuple[int, int]:
    """Return ``(completed_steps, total_steps)`` for a journey."""
    steps = journey_steps(key)
    done = sum(1 for step in steps if completed.get(step.screen))
    return done, len(steps)


def journey_markdown(key: str) -> str:
    """Copy/share Markdown for a role journey (safe, no secrets)."""
    journey = journey_by_key(key)
    lines = [
        f"### {journey.label} journey",
        "",
        f"_{journey.description}_",
        "",
    ]
    for index, step in enumerate(journey.steps, start=1):
        lines.extend(
            [
                f"{index}. **{step.title}** - screen: `{step.screen}`",
                f"   - Goal: {step.goal}",
                f"   - Try it: {step.try_it}",
                f"   - Docs: `{step.doc}`",
            ]
        )
    return "\n".join(lines)


def _demo_history_entry() -> Dict[str, Any]:
    return build_history_entry(DEMO_QUERY, 3, DEMO_RESULT, DEMO_TIMESTAMP)


def demo_seed_state(role: str = DEMO_ROLE) -> Dict[str, Any]:
    """Session-state values that seed a safe, local demo walkthrough."""
    journey = journey_by_key(role)
    entry = _demo_history_entry()
    return {
        "demo_mode": True,
        "demo_role": journey.key,
        "demo_started_at": _now(),
        "journey_state": "running",
        "journey_role": journey.key,
        "journey_step": 0,
        "last_request_id": DEMO_REQUEST_ID,
        "last_query": DEMO_QUERY,
        "last_trace_request_id": DEMO_REQUEST_ID,
        "last_evaluation_at": DEMO_TIMESTAMP,
        "last_governance_seen": True,
        "last_guardrail_at": DEMO_TIMESTAMP,
        "last_audit_at": DEMO_TIMESTAMP,
        "last_admin_at": DEMO_TIMESTAMP,
        "query_history": [entry],
        "qs_last_entry": copy.deepcopy(entry),
        "qs_last_baseline": None,
        "qs_query": DEMO_QUERY,
        "saved_datasets": [copy.deepcopy(DEMO_DATASET)],
        "workspace_scope": {"tenant": DEMO_TENANT, "workspace": DEMO_WORKSPACE},
        "checklist_hidden": False,
    }


def demo_reset_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Clear demo data and workspace state, leaving API/tour settings intact."""
    reset_workspace_state(state)
    state.update(
        {
            "demo_mode": False,
            "demo_role": "",
            "demo_started_at": "",
            "journey_state": "idle",
            "journey_role": "",
            "journey_step": 0,
            "last_request_id": "",
            "last_query": "",
            "last_trace_request_id": "",
            "last_evaluation_at": "",
            "last_governance_seen": False,
            "last_guardrail_at": "",
            "last_audit_at": "",
            "last_admin_at": "",
            "query_history": [],
            "qs_last_entry": None,
            "qs_last_baseline": None,
            "saved_datasets": [],
            "workspace_scope": {"tenant": "", "workspace": ""},
            "workspace_saved_views": {},
            "workspace_saved_runs": [],
            "journey_visited": [],
            "checklist_hidden": False,
        }
    )
    return state


def demo_fixture(path: str, method: str = "GET", payload: Optional[Mapping[str, Any]] = None):
    """Return a local demo fixture for an API path (never touches the network)."""
    payload = payload or {}
    if path == "/health":
        return {"status": "ok", "demo": True}
    if path == "/ready":
        return {
            "status": "ready",
            "config_revision": "demo-0001",
            "components": {"retriever": "faiss", "llm": "demo-llm"},
        }
    if path == "/v1/models":
        return {
            "active": "demo-llm",
            "models": [{"name": "demo-llm", "active": True, "provider": "demo"}],
            "active_config": {
                "name": "demo-llm",
                "context_window": 4096,
                "temperature": 0.0,
                "max_tokens": 512,
            },
        }
    if path == "/v1/embedding-models":
        return {
            "active": "demo-embedder",
            "embedding_models": [
                {
                    "name": "demo-embedder",
                    "active": True,
                    "provider": "demo",
                    "dimension": 384,
                }
            ],
        }
    if path == "/v1/retrievers":
        return {
            "default_retriever": "faiss",
            "similarity_metric": "cosine",
            "providers": ["faiss", "simple"],
            "retrievers": [
                {"key": "faiss", "provider": "faiss", "options": {}},
                {"key": "simple", "provider": "simple", "options": {}},
            ],
        }
    if path == "/v1/rerankers":
        return {
            "enabled": True,
            "active_reranker": "cross-encoder",
            "providers": ["simple"],
            "rerankers": [
                {"key": "cross-encoder", "provider": "simple", "options": {}}
            ],
        }
    if path == "/v1/evaluators":
        return {
            "enabled": True,
            "active_evaluator": "semantic",
            "providers": ["semantic", "llm_judge"],
            "evaluators": [
                {"key": "semantic", "provider": "semantic", "options": {}},
                {"key": "llm_judge", "provider": "llm_judge", "options": {}},
            ],
        }
    if path == "/v1/guardrails":
        return {
            "enabled": True,
            "profile": "standard",
            "providers": ["injection", "deny_list"],
            "input": [{"provider": "injection", "stage": "input"}],
            "output": [{"provider": "deny_list", "stage": "output"}],
            "errors": [],
        }
    if path == "/v1/access":
        return {
            "enabled": True,
            "role": "architect",
            "capabilities": [
                "query",
                "batch",
                "evaluate",
                "experiment",
                "rebuild",
                "introspect",
                "governance",
                "audit",
                "approve",
                "admin",
            ],
            "top_k_max": 10,
            "allowed_models": None,
            "identity_enabled": True,
            "subject": "demo-user",
            "groups": ["demo"],
            "tenant": {
                "id": DEMO_TENANT,
                "workspace": DEMO_WORKSPACE,
                "app": "console",
                "budget_cap_usd": 1.0,
            },
            "request_id": DEMO_REQUEST_ID,
        }
    if path == "/v1/config":
        return {
            "models": {"active_model": "demo-llm"},
            "guardrails": {"enabled": True, "profile": "standard"},
            "demo": True,
        }
    if path == "/v1/query" or path == "/v1/query:batch":
        if path == "/v1/query:batch":
            queries = list(payload.get("queries") or [DEMO_QUERY])
            results = []
            for index, query in enumerate(queries, start=1):
                item = copy.deepcopy(DEMO_RESULT)
                item["request_id"] = f"demo-batch-{index:04d}"
                item["query"] = query
                results.append(item)
            return {
                "results": results,
                "summary": {
                    "batch_size": len(results),
                    "succeeded": len(results),
                    "failed": 0,
                    "by_failure_type": {},
                    "total_cost_usd": 0.00042 * len(results),
                    "total_latency_ms": 842.0 * len(results),
                },
            }
        return copy.deepcopy(DEMO_RESULT)
    if path == "/v1/evaluate":
        return {
            "evaluator": "semantic",
            "ground_truth_used": bool(payload.get("ground_truth")),
            "metrics": {
                "context_precision": 0.81,
                "answer_relevance": 0.88,
                "faithfulness": 0.84,
                "answer_correctness": 0.79,
            },
        }
    if path.startswith("/v1/experiments"):
        return {
            "experiment_id": "demo-experiment-0001",
            "status": "completed",
            "kind": payload.get("kind", "compare_chunking_strategies"),
            "results": {"winner": "small", "rows": []},
        }
    if path == "/v1/pipeline:rebuild":
        return {
            "config_revision": "demo-0002",
            "components": {"retriever": "simple", "llm": "demo-llm"},
            "applied_overrides": dict(payload.get("overrides") or {}),
            "effective_config": {"demo": True},
        }
    if path == "/v1/governance/status":
        return {
            "enabled": True,
            "max_cost_per_request_usd": 0.05,
            "safety_margin_tokens": 128,
            "avg_chunk_tokens": 220,
            "window": {
                "window_seconds": 3600,
                "requests": 1,
                "total_cost_usd": 0.00042,
            },
            "tenant": DEMO_TENANT,
            "demo": True,
        }
    if path.startswith("/v1/traces/"):
        return {
            "request_id": path.rsplit("/", 1)[-1],
            "status": "success",
            "query": DEMO_QUERY,
            "embedding_model": "demo-embedder",
            "retriever": "FAISSRetriever",
            "top_k": 3,
            "reranker": "demo-reranker",
            "retrieved_documents": DEMO_DOCUMENTS,
            "retrieval_scores": [0.92, 0.84],
            "guardrail_decisions": copy.deepcopy(DEMO_RESULT["guardrail_decisions"]),
            "cache_hit": False,
            "latency": {
                "embedding": 41.0,
                "retrieval": 12.0,
                "reranking": 25.0,
                "llm_generation": 700.0,
                "evaluation": 64.0,
                "total_ms": 842.0,
            },
            "observability": copy.deepcopy(DEMO_RESULT["observability"]),
            "demo": True,
        }
    if path == "/v1/metrics":
        return {
            "total_runs": 1,
            "success_count": 1,
            "failure_count": 0,
            "failure_rate": 0.0,
            "latency_ms": {
                "embedding": {"count": 1, "mean": 41.0, "p50": 41.0, "p95": 41.0},
                "llm_generation": {"count": 1, "mean": 700.0, "p50": 700.0, "p95": 700.0},
            },
            "total_latency_ms": {"count": 1, "mean": 842.0, "p50": 842.0, "p95": 842.0},
            "failures_by_type": {},
            "failures_by_tag": {},
            "cost": {"total_usd": 0.00042, "by_model": {"demo-llm": 0.00042}},
            "guardrails": {
                "by_guardrail": {"injection": {"allow": 1, "redact": 0, "block": 0}},
                "by_decision": {"allow": 1, "redact": 0, "block": 0},
                "total_decisions": 1,
                "total_blocks": 0,
            },
            "totals": {
                "requests": 1,
                "successes": 1,
                "failures": 0,
                "cost_usd": 0.00042,
            },
            "by_stage": {"embedding": {"mean": 41.0}, "llm_generation": {"mean": 700.0}},
            "demo": True,
        }
    if path == "/v1/audit":
        return {
            "enabled": True,
            "count": 1,
            "total": 1,
            "events": [
                {
                    "timestamp": DEMO_TIMESTAMP,
                    "event_type": "config",
                    "action": "demo_seed",
                    "outcome": "success",
                    "request_id": DEMO_REQUEST_ID,
                    "tenant": DEMO_TENANT,
                    "details": {},
                }
            ],
            "demo": True,
        }
    if path.startswith("/v1/approvals"):
        if path.endswith("/decision"):
            return {"request_id": path.split("/")[-2], "decision": "approved", "demo": True}
        if path.count("/") > 3:
            return {
                "request_id": path.rsplit("/", 1)[-1],
                "status": "pending",
                "action": "demo.action",
                "reason": "Demo policy gate.",
                "policy": {"id": "demo-policy"},
                "requester": "demo-user",
                "tenant": DEMO_TENANT,
                "workspace": DEMO_WORKSPACE,
                "app": "console",
                "context": {"demo": True},
                "created_at": DEMO_EPOCH,
                "demo": True,
            }
        return {
            "enabled": True,
            "count": 1,
            "total": 1,
            "page": 1,
            "page_size": 50,
            "pages": 1,
            "sort_by": "created_at",
            "order": "desc",
            "requests": [
                {
                    "request_id": DEMO_REQUEST_ID,
                    "action": "demo.action",
                    "status": "pending",
                    "reason": "Demo policy gate.",
                    "policy": {"id": "demo-policy"},
                    "requester": "demo-user",
                    "tenant": DEMO_TENANT,
                    "workspace": DEMO_WORKSPACE,
                    "app": "console",
                    "context": {"demo": True},
                    "created_at": DEMO_EPOCH,
                    "demo": True,
                }
            ],
            "demo": True,
        }
    if path == "/v1/admin/tenants":
        tenant = {
            "id": DEMO_TENANT,
            "workspace": DEMO_WORKSPACE,
            "app": "console",
            "budget_cap_usd": 1.0,
            "top_k_max": 10,
        }
        return {
            "enabled": True,
            "default_tenant": DEMO_TENANT,
            "current": tenant,
            "tenants": [tenant],
            "demo": True,
        }
    if path.startswith("/v1/admin/tenants/"):
        return {"tenant": {"id": path.rsplit("/", 1)[-1]}, "proposal": True, "demo": True}
    if path == "/v1/admin/users":
        return {"users": [{"id": "demo-user", "role": "architect"}], "demo": True}
    if path == "/metrics":
        return {
            "raw": "# demo metrics\ngenai_requests_total{status=\"success\"} 1\n",
            "demo": True,
        }
    return {"demo": True, "path": path, "method": method}
