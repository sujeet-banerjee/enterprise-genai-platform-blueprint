"""Persistent, shareable console workspace (issue #151).

The console keeps a bounded, allowlisted snapshot of the user's working state:
the active screen, query/filter widgets, dataset input, recent runs and saved
views. The snapshot can be shared as a compressed URL blob (``?ws=...``) with
human-readable direct parameters layered on top, or exported as JSON.

This module is deliberately free of Streamlit and backend imports so the state
contract, URL codec, redaction, bounds and scope safety can be unit-tested
without a browser or a live API.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import zlib
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from ui.approvals import (
    AGE_FILTER_OPTIONS,
    ANY_VALUE,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SLA_CRITICAL_HOURS,
    DEFAULT_SLA_WARNING_HOURS,
    DEFAULT_SORT,
    PAGE_SIZE_OPTIONS,
    SORT_OPTIONS,
)
from ui.dataset_studio import normalize_saved_datasets
from ui.navigation import can_access, landing_screen

WORKSPACE_VERSION = 1
URL_STATE_PARAM = "ws"
DEFAULT_SCREEN = "Overview / Health"
DEFAULT_QUERY = "What is retrieval augmented generation?"

MAX_URL_CHARS = 12_000
MAX_EXPORT_BYTES = 256 * 1024
MAX_SAVED_VIEWS_PER_KIND = 5
MAX_RECENT_RUNS = 10
MAX_SAVED_RUNS = 20
MAX_QUERY_CHARS = 2_000
MAX_TEXT_CHARS = 8_000
MAX_DATASET_CHARS = 20_000
MAX_NAME_CHARS = 80
MAX_ID_CHARS = 200

SAVED_VIEW_KINDS: Tuple[str, ...] = (
    "query",
    "compare",
    "evaluation",
    "governance",
    "audit",
    "approvals",
    "traces",
)

VIEW_SCREENS: Dict[str, str] = {
    "query": "Query Studio",
    "compare": "Compare (what-if)",
    "evaluation": "Evaluation",
    "governance": "Governance & Cost",
    "audit": "Audit",
    "approvals": "Approvals",
    "traces": "Traces",
}

VIEW_SECTIONS: Dict[str, str] = {
    "query": "query_studio",
    "compare": "compare",
    "evaluation": "evaluation",
    "governance": "governance",
    "audit": "audit",
    "approvals": "approvals",
    "traces": "traces",
}

DIRECT_PARAMS: Tuple[str, ...] = (
    "screen",
    "q",
    "top_k",
    "include_trace",
    "batch",
    "request_id",
    "tenant",
    "workspace",
    "cmp_metric",
    "cmp_retriever",
    "cmp_query",
    "eval_query",
    "eval_evaluator",
    "eval_dataset_choice",
    "eval_dataset_source",
    "eval_dataset_evaluator",
    "eval_dataset_top_k",
    "eval_job",
    "gov_time",
    "gov_tenant",
    "gov_app",
    "gov_user",
    "gov_request",
    "audit_limit",
    "audit_event",
    "audit_request",
    "approval_status",
    "approval_request",
    "approval_action",
    "approval_policy",
    "approval_requester",
    "approval_tenant",
    "approval_age",
    "approval_search",
    "approval_sort",
    "approval_page",
    "approval_page_size",
    "approval_warning_hours",
    "approval_critical_hours",
    "traces_request_id",
    "traces_compare",
)

MANAGED_PARAMS = frozenset((URL_STATE_PARAM,) + DIRECT_PARAMS)

_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*"
    r'|"?(?:api[_-]?key|secret|token|password)"?\s*[:=]\s*"?[^\s,;"]+)',
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ID_RE = re.compile(r"[^A-Za-z0-9._:@/+=-]+")

_RESERVED_KEYS = frozenset(
    {
        "version",
        "screen",
        "scope",
        "query_studio",
        "compare",
        "evaluation",
        "governance",
        "audit",
        "approvals",
        "traces",
        "activity",
        "recent_runs",
        "saved_runs",
        "saved_views",
    }
)


class WorkspaceError(ValueError):
    """Raised when a workspace cannot be decoded, imported or shared."""


def _clean_text(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = _CONTROL_RE.sub("", value)
    value = _SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value.strip()[:max_chars]


def _clean_id(value: Any) -> str:
    return _ID_RE.sub("", _clean_text(value, MAX_ID_CHARS))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 6)


def _as_hours(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    return round(max(0.1, min(720.0, parsed)), 2)


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if value is None:
        return ""
    return str(value)


def _normalize_scope(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {"tenant": "", "workspace": ""}
    tenant = _clean_id(value.get("tenant"))
    workspace = _clean_id(value.get("workspace"))
    if tenant.lower() == "default":
        tenant = ""
    if workspace.lower() == "default":
        workspace = ""
    return {"tenant": tenant, "workspace": workspace}


def _normalize_query_studio(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    query = _clean_text(data.get("query"), MAX_QUERY_CHARS) or DEFAULT_QUERY
    return {
        "query": query,
        "top_k": _as_int(data.get("top_k"), 3, 1, 10),
        "include_trace": _as_bool(data.get("include_trace"), True),
        "batch": _as_bool(data.get("batch"), False),
    }


def _normalize_compare(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    return {
        "metric": _clean_text(data.get("metric"), 40) or "(keep)",
        "retriever": _clean_text(data.get("retriever"), 60) or "(keep)",
        "query": _clean_text(data.get("query"), MAX_QUERY_CHARS) or DEFAULT_QUERY,
    }


def _normalize_evaluation(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    source = _clean_text(data.get("dataset_source"), 40)
    if source not in ("Built-in benchmark", "Paste JSON", "Dataset Studio"):
        source = "Built-in benchmark"
    return {
        "query": _clean_text(data.get("query"), MAX_QUERY_CHARS) or DEFAULT_QUERY,
        "response": _clean_text(data.get("response"), MAX_TEXT_CHARS)
        or "RAG grounds an LLM on retrieved documents.",
        "ground_truth": _clean_text(data.get("ground_truth"), MAX_TEXT_CHARS),
        "evaluator": _clean_text(data.get("evaluator"), 80) or "(active)",
        "dataset_choice": _clean_text(data.get("dataset_choice"), 120)
        or "Built-in benchmark",
        "dataset_source": source,
        "dataset_json": _clean_text(data.get("dataset_json"), MAX_DATASET_CHARS),
        "dataset_evaluator": _clean_text(data.get("dataset_evaluator"), 80) or "(active)",
        "dataset_top_k": _as_int(data.get("dataset_top_k"), 3, 1, 10),
        "job_id": _clean_id(data.get("job_id")),
        "datasets": normalize_saved_datasets(data.get("datasets")),
    }


def _normalize_governance(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    return {
        "time_range": _clean_text(data.get("time_range"), 40) or "Last hour",
        "tenant": _clean_text(data.get("tenant"), 80),
        "app": _clean_text(data.get("app"), 80),
        "user": _clean_text(data.get("user"), 80),
        "request_id": _clean_id(data.get("request_id")),
    }


def _normalize_audit(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    return {
        "limit": _as_int(data.get("limit"), 50, 1, 1000),
        "event_type": _clean_text(data.get("event_type"), 80),
        "request_id": _clean_id(data.get("request_id")),
    }


def _normalize_approvals(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    status = _clean_text(data.get("status"), 40).lower()
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    age = _clean_text(data.get("age"), 40)
    if age not in AGE_FILTER_OPTIONS:
        age = AGE_FILTER_OPTIONS[0]
    sort_by = _clean_text(data.get("sort"), 60)
    if sort_by not in SORT_OPTIONS:
        sort_by = DEFAULT_SORT
    page_size = _as_int(data.get("page_size"), DEFAULT_PAGE_SIZE, 1, 500)
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = DEFAULT_PAGE_SIZE
    warning_hours = _as_hours(
        data.get("warning_hours"), DEFAULT_SLA_WARNING_HOURS
    )
    critical_hours = _as_hours(
        data.get("critical_hours"), DEFAULT_SLA_CRITICAL_HOURS
    )
    if critical_hours < warning_hours:
        critical_hours = warning_hours
    return {
        "status": status,
        "request_id": _clean_id(data.get("request_id")),
        "action": _clean_text(data.get("action"), 120) or ANY_VALUE,
        "policy": _clean_text(data.get("policy"), 120) or ANY_VALUE,
        "requester": _clean_text(data.get("requester"), 120) or ANY_VALUE,
        "tenant": _clean_text(data.get("tenant"), 80) or ANY_VALUE,
        "age": age,
        "search": _clean_text(data.get("search"), 200),
        "sort": sort_by,
        "page": _as_int(data.get("page"), 1, 1, 100_000),
        "page_size": page_size,
        "warning_hours": warning_hours,
        "critical_hours": critical_hours,
    }


def _normalize_traces(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    return {
        "request_id": _clean_id(data.get("request_id")),
        "compare_request_id": _clean_id(data.get("compare_request_id")),
    }


def _normalize_activity(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, Mapping) else {}
    return {
        "last_request_id": _clean_id(data.get("last_request_id")),
        "last_query": _clean_text(data.get("last_query"), MAX_QUERY_CHARS),
        "last_trace_request_id": _clean_id(data.get("last_trace_request_id")),
        "last_evaluation_at": _clean_text(data.get("last_evaluation_at"), 80),
        "last_governance_seen": _as_bool(data.get("last_governance_seen"), False),
    }


def _normalize_section(kind: str, value: Any) -> Dict[str, Any]:
    if kind == "query":
        return _normalize_query_studio(value)
    if kind == "compare":
        return _normalize_compare(value)
    if kind == "evaluation":
        return _normalize_evaluation(value)
    if kind == "governance":
        return _normalize_governance(value)
    if kind == "audit":
        return _normalize_audit(value)
    if kind == "approvals":
        return _normalize_approvals(value)
    if kind == "traces":
        return _normalize_traces(value)
    raise WorkspaceError(f"Unknown saved-view kind: {kind}")


def _normalize_run(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    request_id = _clean_id(value.get("request_id"))
    query = _clean_text(value.get("query"), MAX_QUERY_CHARS)
    if not request_id and not query:
        return None
    outcome = _clean_text(value.get("outcome"), 20).lower()
    if outcome not in ("success", "failure"):
        outcome = "failure" if value.get("failure_type") else "success"
    return {
        "request_id": request_id,
        "query": query,
        "top_k": _as_int(value.get("top_k"), 3, 1, 10),
        "timestamp": _clean_text(value.get("timestamp"), 64),
        "outcome": outcome,
        "failure_type": _clean_id(value.get("failure_type")),
        "latency_ms": _as_float(value.get("latency_ms")),
        "cost_usd": _as_float(value.get("cost_usd")),
        "doc_count": _as_int(value.get("doc_count"), 0, 0, 1_000_000),
        "cache_hit": _as_bool(value.get("cache_hit"), False),
        "guardrail_decisions": _as_int(value.get("guardrail_decisions"), 0, 0, 1_000_000),
        "guardrail_blocks": _as_int(value.get("guardrail_blocks"), 0, 0, 1_000_000),
    }


def _dedupe_runs(values: Any, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for value in values:
        run = _normalize_run(value)
        if run is None:
            continue
        key = run["request_id"] or f"{run['query']}|{run['timestamp']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(run)
        if len(out) >= limit:
            break
    return out


def _normalize_saved_views(value: Any) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in SAVED_VIEW_KINDS}
    if not isinstance(value, Mapping):
        return result
    for kind in SAVED_VIEW_KINDS:
        entries = value.get(kind)
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            continue
        seen = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            name = _clean_text(entry.get("name"), MAX_NAME_CHARS)
            section = _clean_text(entry.get("section"), 40) or VIEW_SECTIONS[kind]
            if not name or name.lower() in seen or section != VIEW_SECTIONS[kind]:
                continue
            values = _normalize_section(kind, entry.get("values"))
            result[kind].append(
                {
                    "name": name,
                    "screen": VIEW_SCREENS[kind],
                    "section": section,
                    "values": values,
                }
            )
            seen.add(name.lower())
            if len(result[kind]) >= MAX_SAVED_VIEWS_PER_KIND:
                break
    return result


def empty_workspace() -> Dict[str, Any]:
    """Return a fresh, versioned workspace with allowlisted defaults."""
    return {
        "version": WORKSPACE_VERSION,
        "screen": DEFAULT_SCREEN,
        "scope": {"tenant": "", "workspace": ""},
        "query_studio": _normalize_query_studio({}),
        "compare": _normalize_compare({}),
        "evaluation": _normalize_evaluation({}),
        "governance": _normalize_governance({}),
        "audit": _normalize_audit({}),
        "approvals": _normalize_approvals({}),
        "traces": _normalize_traces({}),
        "activity": _normalize_activity({}),
        "recent_runs": [],
        "saved_runs": [],
        "saved_views": {kind: [] for kind in SAVED_VIEW_KINDS},
    }


def normalize_workspace(value: Any) -> Dict[str, Any]:
    """Normalize an untrusted workspace mapping, dropping unknown/secret keys."""
    if not isinstance(value, Mapping):
        return empty_workspace()
    version = value.get("version", WORKSPACE_VERSION)
    if version not in (None, WORKSPACE_VERSION):
        raise WorkspaceError(f"Unsupported workspace version: {version}")
    return {
        "version": WORKSPACE_VERSION,
        "screen": _clean_text(value.get("screen"), 80) or DEFAULT_SCREEN,
        "scope": _normalize_scope(value.get("scope")),
        "query_studio": _normalize_query_studio(value.get("query_studio")),
        "compare": _normalize_compare(value.get("compare")),
        "evaluation": _normalize_evaluation(value.get("evaluation")),
        "governance": _normalize_governance(value.get("governance")),
        "audit": _normalize_audit(value.get("audit")),
        "approvals": _normalize_approvals(value.get("approvals")),
        "traces": _normalize_traces(value.get("traces")),
        "activity": _normalize_activity(value.get("activity")),
        "recent_runs": _dedupe_runs(value.get("recent_runs"), MAX_RECENT_RUNS),
        "saved_runs": _dedupe_runs(value.get("saved_runs"), MAX_SAVED_RUNS),
        "saved_views": _normalize_saved_views(value.get("saved_views")),
    }


def _scope_from_access(access: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    tenant = (access or {}).get("tenant") or {}
    if not isinstance(tenant, Mapping):
        tenant = {}
    return _normalize_scope(
        {
            "tenant": tenant.get("id") or tenant.get("tenant") or "",
            "workspace": tenant.get("workspace") or "",
        }
    )


def workspace_from_session(
    state: Mapping[str, Any],
    scope: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a bounded workspace snapshot from the Streamlit session state."""
    workspace = empty_workspace()
    workspace["screen"] = _clean_text(state.get("active_screen"), 80) or DEFAULT_SCREEN
    workspace["scope"] = _normalize_scope(
        scope if scope is not None else state.get("workspace_scope")
    )
    workspace["query_studio"] = _normalize_query_studio(
        {
            "query": state.get("qs_query"),
            "top_k": state.get("qs_top_k"),
            "include_trace": state.get("qs_include_trace"),
            "batch": state.get("qs_batch"),
        }
    )
    workspace["compare"] = _normalize_compare(
        {
            "metric": state.get("cmp_metric"),
            "retriever": state.get("cmp_retriever"),
            "query": state.get("cmp_query"),
        }
    )
    workspace["evaluation"] = _normalize_evaluation(
        {
            "query": state.get("eval_query"),
            "response": state.get("eval_response"),
            "ground_truth": state.get("eval_ground_truth"),
            "evaluator": state.get("eval_evaluator"),
            "dataset_choice": state.get("evaluation_dataset_choice"),
            "dataset_source": state.get("evaluation_dataset_source"),
            "dataset_json": state.get("evaluation_dataset_json"),
            "dataset_evaluator": state.get("dataset_evaluator"),
            "dataset_top_k": state.get("dataset_top_k"),
            "job_id": state.get("eval_job_id"),
            "datasets": state.get("saved_datasets"),
        }
    )
    workspace["governance"] = _normalize_governance(
        {
            "time_range": state.get("gov_time_range"),
            "tenant": state.get("gov_tenant"),
            "app": state.get("gov_app"),
            "user": state.get("gov_user"),
            "request_id": state.get("gov_request_id"),
        }
    )
    workspace["audit"] = _normalize_audit(
        {
            "limit": state.get("audit_limit"),
            "event_type": state.get("audit_event_type"),
            "request_id": state.get("audit_request_id"),
        }
    )
    workspace["approvals"] = _normalize_approvals(
        {
            "status": state.get("approval_status"),
            "request_id": state.get("approval_request_id"),
            "action": state.get("approval_action"),
            "policy": state.get("approval_policy"),
            "requester": state.get("approval_requester"),
            "tenant": state.get("approval_tenant"),
            "age": state.get("approval_age"),
            "search": state.get("approval_search"),
            "sort": state.get("approval_sort"),
            "page": state.get("approval_page"),
            "page_size": state.get("approval_page_size"),
            "warning_hours": state.get("approval_warning_hours"),
            "critical_hours": state.get("approval_critical_hours"),
        }
    )
    workspace["traces"] = _normalize_traces(
        {
            "request_id": state.get("trace_request_id") or state.get("last_trace_request_id"),
            "compare_request_id": state.get("trace_compare_request_id"),
        }
    )
    workspace["activity"] = _normalize_activity(
        {
            "last_request_id": state.get("last_request_id"),
            "last_query": state.get("last_query"),
            "last_trace_request_id": state.get("last_trace_request_id"),
            "last_evaluation_at": state.get("last_evaluation_at"),
            "last_governance_seen": state.get("last_governance_seen"),
        }
    )
    workspace["recent_runs"] = _dedupe_runs(
        state.get("query_history") or [], MAX_RECENT_RUNS
    )
    workspace["saved_runs"] = _dedupe_runs(
        state.get("workspace_saved_runs") or [], MAX_SAVED_RUNS
    )
    workspace["saved_views"] = _normalize_saved_views(state.get("workspace_saved_views"))
    return workspace


def workspace_scope_matches(
    workspace: Mapping[str, Any],
    access: Optional[Mapping[str, Any]],
) -> bool:
    """Whether a link's tenant/workspace scope matches the current caller."""
    expected = _normalize_scope((workspace or {}).get("scope"))
    if not expected["tenant"] and not expected["workspace"]:
        return True
    if not access or not access.get("ok"):
        return True
    return expected == _scope_from_access(access)


def scope_safe_workspace(
    workspace: Mapping[str, Any],
    access: Optional[Mapping[str, Any]],
    screens: Sequence[str],
) -> Tuple[Dict[str, Any], str]:
    """Drop tenant-specific state when a link belongs to another scope."""
    normalized = normalize_workspace(workspace)
    if workspace_scope_matches(normalized, access):
        return normalized, ""
    fallback = empty_workspace()
    screen = normalized["screen"]
    if screen in screens and can_access(screen, (access or {}).get("capabilities") or []):
        fallback["screen"] = screen
    return fallback, (
        "This link was created for a different tenant/workspace. "
        "Tenant-specific state was ignored; authenticate in the link's scope to restore it."
    )


def _trace_request_id(workspace: Mapping[str, Any]) -> str:
    traces = workspace.get("traces") or {}
    activity = workspace.get("activity") or {}
    return (
        _clean_id(traces.get("request_id"))
        or _clean_id(activity.get("last_trace_request_id"))
        or _clean_id(activity.get("last_request_id"))
    )


def _trace_compare_request_id(workspace: Mapping[str, Any]) -> str:
    traces = workspace.get("traces") or {}
    return _clean_id(traces.get("compare_request_id"))


def apply_workspace(
    workspace: Mapping[str, Any],
    state: MutableMapping[str, Any],
    access: Optional[Mapping[str, Any]],
    screens: Sequence[str],
) -> str:
    """Apply a workspace to session state and return the resolved screen."""
    safe, warning = scope_safe_workspace(workspace, access, screens)
    capabilities = (access or {}).get("capabilities") or []
    ordered = list(screens)
    screen = safe["screen"]
    if screen not in ordered or not can_access(screen, capabilities):
        screen = landing_screen((access or {}).get("role") or "admin", capabilities, ordered)

    query_studio = safe["query_studio"]
    compare = safe["compare"]
    evaluation = safe["evaluation"]
    governance = safe["governance"]
    audit = safe["audit"]
    approvals = safe["approvals"]
    activity = safe["activity"]

    state["active_screen"] = screen
    state["nav_initialized"] = True
    state["qs_query"] = query_studio["query"]
    state["qs_top_k"] = query_studio["top_k"]
    state["qs_include_trace"] = query_studio["include_trace"]
    state["qs_batch"] = query_studio["batch"]
    state["cmp_metric"] = compare["metric"]
    state["cmp_retriever"] = compare["retriever"]
    state["cmp_query"] = compare["query"]
    state["eval_query"] = evaluation["query"]
    state["eval_response"] = evaluation["response"]
    state["eval_ground_truth"] = evaluation["ground_truth"]
    state["eval_evaluator"] = evaluation["evaluator"]
    state["evaluation_dataset_choice"] = evaluation["dataset_choice"]
    state["evaluation_dataset_source"] = evaluation["dataset_source"]
    state["evaluation_dataset_json"] = evaluation["dataset_json"]
    state["dataset_evaluator"] = evaluation["dataset_evaluator"]
    state["dataset_top_k"] = evaluation["dataset_top_k"]
    state["eval_job_id"] = evaluation["job_id"]
    state["saved_datasets"] = copy.deepcopy(evaluation["datasets"])
    state["gov_time_range"] = governance["time_range"]
    state["gov_tenant"] = governance["tenant"]
    state["gov_app"] = governance["app"]
    state["gov_user"] = governance["user"]
    state["gov_request_id"] = governance["request_id"]
    state["audit_limit"] = audit["limit"]
    state["audit_event_type"] = audit["event_type"]
    state["audit_request_id"] = audit["request_id"]
    state["approval_status"] = approvals["status"]
    state["approval_request_id"] = approvals["request_id"]
    state["approval_action"] = approvals["action"]
    state["approval_policy"] = approvals["policy"]
    state["approval_requester"] = approvals["requester"]
    state["approval_tenant"] = approvals["tenant"]
    state["approval_age"] = approvals["age"]
    state["approval_search"] = approvals["search"]
    state["approval_sort"] = approvals["sort"]
    state["approval_page"] = approvals["page"]
    state["approval_page_size"] = approvals["page_size"]
    state["approval_warning_hours"] = approvals["warning_hours"]
    state["approval_critical_hours"] = approvals["critical_hours"]
    state["approval_bulk_ids"] = []
    state["last_request_id"] = activity["last_request_id"]
    state["last_query"] = activity["last_query"]
    state["last_trace_request_id"] = activity["last_trace_request_id"]
    state["last_evaluation_at"] = activity["last_evaluation_at"]
    state["last_governance_seen"] = activity["last_governance_seen"]
    state["trace_request_id"] = _trace_request_id(safe)
    state["trace_compare_request_id"] = _trace_compare_request_id(safe)
    state["trace_autoload"] = screen == "Traces" and bool(state["trace_request_id"])
    state["trace_compare_autoload"] = (
        screen == "Traces"
        and bool(state["trace_request_id"])
        and bool(state["trace_compare_request_id"])
    )
    state["query_history"] = [dict(run) for run in safe["recent_runs"]]
    state["qs_last_entry"] = None
    state["qs_last_baseline"] = None
    state["workspace_scope"] = dict(safe["scope"])
    state["workspace_saved_views"] = copy.deepcopy(safe["saved_views"])
    state["workspace_saved_runs"] = copy.deepcopy(safe["saved_runs"])
    state["workspace_notice"] = warning
    state["workspace_last_applied_signature"] = workspace_signature(safe)
    return screen


def _state_defaults() -> Dict[str, Any]:
    workspace = empty_workspace()
    query_studio = workspace["query_studio"]
    compare = workspace["compare"]
    evaluation = workspace["evaluation"]
    governance = workspace["governance"]
    audit = workspace["audit"]
    approvals = workspace["approvals"]
    return {
        "active_screen": DEFAULT_SCREEN,
        "nav_initialized": False,
        "qs_query": query_studio["query"],
        "qs_top_k": query_studio["top_k"],
        "qs_include_trace": query_studio["include_trace"],
        "qs_batch": query_studio["batch"],
        "query_history": [],
        "qs_last_entry": None,
        "qs_last_baseline": None,
        "cmp_metric": compare["metric"],
        "cmp_retriever": compare["retriever"],
        "cmp_query": compare["query"],
        "eval_query": evaluation["query"],
        "eval_response": evaluation["response"],
        "eval_ground_truth": evaluation["ground_truth"],
        "eval_evaluator": evaluation["evaluator"],
        "evaluation_dataset_choice": evaluation["dataset_choice"],
        "evaluation_dataset_source": evaluation["dataset_source"],
        "dataset_evaluator": evaluation["dataset_evaluator"],
        "dataset_top_k": evaluation["dataset_top_k"],
        "eval_job_id": evaluation["job_id"],
        "saved_datasets": [],
        "gov_time_range": governance["time_range"],
        "gov_tenant": governance["tenant"],
        "gov_app": governance["app"],
        "gov_user": governance["user"],
        "gov_request_id": governance["request_id"],
        "audit_limit": audit["limit"],
        "audit_event_type": audit["event_type"],
        "audit_request_id": audit["request_id"],
        "approval_status": approvals["status"],
        "approval_request_id": approvals["request_id"],
        "approval_action": approvals["action"],
        "approval_policy": approvals["policy"],
        "approval_requester": approvals["requester"],
        "approval_tenant": approvals["tenant"],
        "approval_age": approvals["age"],
        "approval_search": approvals["search"],
        "approval_sort": approvals["sort"],
        "approval_page": approvals["page"],
        "approval_page_size": approvals["page_size"],
        "approval_warning_hours": approvals["warning_hours"],
        "approval_critical_hours": approvals["critical_hours"],
        "approval_bulk_ids": [],
        "trace_request_id": "",
        "trace_compare_request_id": "",
        "trace_autoload": False,
        "trace_compare_autoload": False,
        "workspace_scope": {"tenant": "", "workspace": ""},
        "workspace_saved_views": {kind: [] for kind in SAVED_VIEW_KINDS},
        "workspace_saved_runs": [],
        "workspace_notice": "",
        "workspace_last_applied_signature": "",
    }


def ensure_state_defaults(state: MutableMapping[str, Any]) -> None:
    """Fill only missing workspace/widget keys; never overwrite user state."""
    for key, value in _state_defaults().items():
        if key not in state:
            state[key] = copy.deepcopy(value)


def reset_workspace_state(state: MutableMapping[str, Any]) -> None:
    """Reset workspace and form state while preserving API/tour settings."""
    for key, value in _state_defaults().items():
        state[key] = copy.deepcopy(value)
    state["active_screen"] = DEFAULT_SCREEN
    state["nav_initialized"] = True
    state["evaluation_dataset_json"] = ""
    state["workspace_notice"] = ""
    state["workspace_synced_signature"] = ""
    state["workspace_last_applied_signature"] = ""


def add_saved_view(workspace: Mapping[str, Any], kind: str, name: str) -> Dict[str, Any]:
    """Capture the current section as a named saved view (newest first, capped)."""
    if kind not in SAVED_VIEW_KINDS:
        raise WorkspaceError(f"Unknown saved-view kind: {kind}")
    clean_name = _clean_text(name, MAX_NAME_CHARS)
    if not clean_name:
        raise WorkspaceError("Saved view name is required")
    normalized = normalize_workspace(workspace)
    section = VIEW_SECTIONS[kind]
    entry = {
        "name": clean_name,
        "screen": VIEW_SCREENS[kind],
        "section": section,
        "values": copy.deepcopy(normalized[section]),
    }
    existing = [
        item
        for item in normalized["saved_views"][kind]
        if item.get("name", "").lower() != clean_name.lower()
    ]
    normalized["saved_views"][kind] = ([entry] + existing)[:MAX_SAVED_VIEWS_PER_KIND]
    return normalized


def remove_saved_view(workspace: Mapping[str, Any], kind: str, name: str) -> Dict[str, Any]:
    """Remove a saved view by case-insensitive name."""
    normalized = normalize_workspace(workspace)
    if kind not in SAVED_VIEW_KINDS:
        raise WorkspaceError(f"Unknown saved-view kind: {kind}")
    clean_name = _clean_text(name, MAX_NAME_CHARS).lower()
    normalized["saved_views"][kind] = [
        entry
        for entry in normalized["saved_views"][kind]
        if entry.get("name", "").lower() != clean_name
    ]
    return normalized


def saved_views_for(workspace: Mapping[str, Any], kind: str) -> List[Dict[str, Any]]:
    """Return a copy of the saved views for one section."""
    if kind not in SAVED_VIEW_KINDS:
        raise WorkspaceError(f"Unknown saved-view kind: {kind}")
    return copy.deepcopy(normalize_workspace(workspace)["saved_views"][kind])


def apply_saved_view(workspace: Mapping[str, Any], kind: str, name: str) -> Dict[str, Any]:
    """Return a workspace with one saved view applied, preserving other state."""
    normalized = normalize_workspace(workspace)
    if kind not in SAVED_VIEW_KINDS:
        raise WorkspaceError(f"Unknown saved-view kind: {kind}")
    clean_name = _clean_text(name, MAX_NAME_CHARS).lower()
    for entry in normalized["saved_views"][kind]:
        if entry.get("name", "").lower() == clean_name:
            normalized["screen"] = entry["screen"]
            normalized[entry["section"]] = _normalize_section(kind, entry["values"])
            return normalized
    return normalized


def add_recent_run(workspace: Mapping[str, Any], entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Add a compact run summary to the bounded recent-runs list."""
    normalized = normalize_workspace(workspace)
    run = _normalize_run(entry)
    if run is None:
        return normalized
    normalized["recent_runs"] = _dedupe_runs(
        [run] + normalized["recent_runs"], MAX_RECENT_RUNS
    )
    return normalized


def add_saved_run(workspace: Mapping[str, Any], entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Save/pin a compact run summary (newest first, deduped, capped)."""
    normalized = normalize_workspace(workspace)
    run = _normalize_run(entry)
    if run is None:
        return normalized
    normalized["saved_runs"] = _dedupe_runs(
        [run] + normalized["saved_runs"], MAX_SAVED_RUNS
    )
    return normalized


def remove_saved_run(workspace: Mapping[str, Any], request_id: str) -> Dict[str, Any]:
    """Remove a saved run by request id."""
    normalized = normalize_workspace(workspace)
    clean_id = _clean_id(request_id)
    normalized["saved_runs"] = [
        run for run in normalized["saved_runs"] if run.get("request_id") != clean_id
    ]
    return normalized


def is_run_saved(workspace: Mapping[str, Any], request_id: str) -> bool:
    """Whether a run is already pinned in saved runs."""
    clean_id = _clean_id(request_id)
    return any(
        run.get("request_id") == clean_id
        for run in normalize_workspace(workspace)["saved_runs"]
        if clean_id
    )


def _canonical(workspace: Mapping[str, Any]) -> str:
    return json.dumps(
        normalize_workspace(workspace),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def workspace_signature(workspace: Mapping[str, Any]) -> str:
    """Stable hash of the normalized workspace (used to avoid URL sync loops)."""
    return hashlib.sha256(_canonical(workspace).encode("utf-8")).hexdigest()


def encode_workspace(workspace: Mapping[str, Any]) -> str:
    """Encode a workspace as a URL-safe, compressed token."""
    raw = _canonical(workspace).encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")


def decode_workspace(token: str) -> Dict[str, Any]:
    """Decode a workspace token, rejecting corrupt or oversized payloads."""
    if not isinstance(token, str) or not token.strip():
        raise WorkspaceError("Workspace token is empty")
    padded = token.strip() + "=" * (-len(token.strip()) % 4)
    try:
        compressed = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise WorkspaceError("Workspace token is not valid base64") from exc
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, MAX_EXPORT_BYTES + 1)
        raw += inflater.flush()
    except zlib.error as exc:
        raise WorkspaceError("Workspace token is not valid compressed data") from exc
    if inflater.unconsumed_tail or len(raw) > MAX_EXPORT_BYTES:
        raise WorkspaceError("Workspace payload is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError("Workspace payload is not valid JSON") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("Workspace payload must be an object")
    version = data.get("version", WORKSPACE_VERSION)
    if version != WORKSPACE_VERSION:
        raise WorkspaceError(f"Unsupported workspace version: {version}")
    return normalize_workspace(data)


def workspace_from_query_params(
    params: Mapping[str, Any],
    screens: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Parse a workspace from Streamlit query parameters (direct keys win)."""
    del screens  # Screen access is validated by apply_workspace.
    workspace = empty_workspace()
    token = _first((params or {}).get(URL_STATE_PARAM)) if params else ""
    if token:
        try:
            workspace = decode_workspace(token)
        except WorkspaceError:
            workspace = empty_workspace()

    query_studio = workspace["query_studio"]
    compare = workspace["compare"]
    evaluation = workspace["evaluation"]
    governance = workspace["governance"]
    audit = workspace["audit"]
    approvals = workspace["approvals"]
    scope = workspace["scope"]

    def has(key: str) -> bool:
        return bool(params) and key in params

    def value(key: str) -> str:
        return _first(params.get(key)) if params else ""

    if has("screen") and value("screen").strip():
        workspace["screen"] = _clean_text(value("screen"), 80)
    if has("q"):
        query_studio["query"] = _clean_text(value("q"), MAX_QUERY_CHARS)
    if has("top_k"):
        query_studio["top_k"] = _as_int(value("top_k"), query_studio["top_k"], 1, 10)
    if has("include_trace"):
        query_studio["include_trace"] = _as_bool(value("include_trace"), True)
    if has("batch"):
        query_studio["batch"] = _as_bool(value("batch"), False)
    if has("cmp_metric"):
        compare["metric"] = _clean_text(value("cmp_metric"), 40)
    if has("cmp_retriever"):
        compare["retriever"] = _clean_text(value("cmp_retriever"), 60)
    if has("cmp_query"):
        compare["query"] = _clean_text(value("cmp_query"), MAX_QUERY_CHARS)
    if has("eval_query"):
        evaluation["query"] = _clean_text(value("eval_query"), MAX_QUERY_CHARS)
    if has("eval_evaluator"):
        evaluation["evaluator"] = _clean_text(value("eval_evaluator"), 80)
    if has("eval_dataset_choice"):
        evaluation["dataset_choice"] = _clean_text(value("eval_dataset_choice"), 120)
    if has("eval_dataset_source"):
        source = _clean_text(value("eval_dataset_source"), 40)
        if source in ("Built-in benchmark", "Paste JSON", "Dataset Studio"):
            evaluation["dataset_source"] = source
    if has("eval_dataset_evaluator"):
        evaluation["dataset_evaluator"] = _clean_text(
            value("eval_dataset_evaluator"), 80
        )
    if has("eval_dataset_top_k"):
        evaluation["dataset_top_k"] = _as_int(
            value("eval_dataset_top_k"), evaluation["dataset_top_k"], 1, 10
        )
    if has("eval_job"):
        evaluation["job_id"] = _clean_id(value("eval_job"))
    if has("gov_time"):
        governance["time_range"] = _clean_text(value("gov_time"), 40)
    if has("gov_tenant"):
        governance["tenant"] = _clean_text(value("gov_tenant"), 80)
    if has("gov_app"):
        governance["app"] = _clean_text(value("gov_app"), 80)
    if has("gov_user"):
        governance["user"] = _clean_text(value("gov_user"), 80)
    if has("gov_request"):
        governance["request_id"] = _clean_id(value("gov_request"))
    if has("audit_limit"):
        audit["limit"] = _as_int(value("audit_limit"), audit["limit"], 1, 1000)
    if has("audit_event"):
        audit["event_type"] = _clean_text(value("audit_event"), 80)
    if has("audit_request"):
        audit["request_id"] = _clean_id(value("audit_request"))
    if has("approval_status"):
        approvals["status"] = _normalize_approvals(
            {"status": value("approval_status")}
        )["status"]
    if has("approval_request"):
        approvals["request_id"] = _clean_id(value("approval_request"))
    if has("approval_action"):
        approvals["action"] = _clean_text(value("approval_action"), 120) or ANY_VALUE
    if has("approval_policy"):
        approvals["policy"] = _clean_text(value("approval_policy"), 120) or ANY_VALUE
    if has("approval_requester"):
        approvals["requester"] = (
            _clean_text(value("approval_requester"), 120) or ANY_VALUE
        )
    if has("approval_tenant"):
        approvals["tenant"] = _clean_text(value("approval_tenant"), 80) or ANY_VALUE
    if has("approval_age"):
        approvals["age"] = _normalize_approvals(
            {"age": value("approval_age")}
        )["age"]
    if has("approval_search"):
        approvals["search"] = _clean_text(value("approval_search"), 200)
    if has("approval_sort"):
        approvals["sort"] = _normalize_approvals(
            {"sort": value("approval_sort")}
        )["sort"]
    if has("approval_page"):
        approvals["page"] = _as_int(value("approval_page"), approvals["page"], 1, 100_000)
    if has("approval_page_size"):
        approvals["page_size"] = _normalize_approvals(
            {"page_size": value("approval_page_size")}
        )["page_size"]
    if has("approval_warning_hours"):
        approvals["warning_hours"] = _as_hours(
            value("approval_warning_hours"), approvals["warning_hours"]
        )
    if has("approval_critical_hours"):
        approvals["critical_hours"] = _as_hours(
            value("approval_critical_hours"), approvals["critical_hours"]
        )
    if has("tenant"):
        scope["tenant"] = _normalize_scope({"tenant": value("tenant")})["tenant"]
    if has("workspace"):
        scope["workspace"] = _normalize_scope({"workspace": value("workspace")})["workspace"]
    if has("traces_request_id"):
        workspace["traces"]["request_id"] = _clean_id(value("traces_request_id"))
    if has("traces_compare"):
        workspace["traces"]["compare_request_id"] = _clean_id(value("traces_compare"))
    if has("request_id"):
        workspace["traces"]["request_id"] = _clean_id(value("request_id"))
    return normalize_workspace(workspace)


def workspace_to_query_params(
    workspace: Mapping[str, Any],
    include_blob: bool = True,
) -> Dict[str, str]:
    """Build readable direct parameters plus an optional compressed blob."""
    normalized = normalize_workspace(workspace)
    query_studio = normalized["query_studio"]
    compare = normalized["compare"]
    evaluation = normalized["evaluation"]
    governance = normalized["governance"]
    audit = normalized["audit"]
    approvals = normalized["approvals"]
    scope = normalized["scope"]
    params: Dict[str, str] = {}
    if include_blob:
        params[URL_STATE_PARAM] = encode_workspace(normalized)
    params["screen"] = normalized["screen"]
    if query_studio["query"]:
        params["q"] = query_studio["query"]
    params["top_k"] = str(query_studio["top_k"])
    params["include_trace"] = "1" if query_studio["include_trace"] else "0"
    params["batch"] = "1" if query_studio["batch"] else "0"
    if normalized["screen"] == "Traces":
        request_id = _trace_request_id(normalized)
        if request_id:
            params["request_id"] = request_id
        compare_request_id = _trace_compare_request_id(normalized)
        if compare_request_id:
            params["traces_compare"] = compare_request_id
    if scope["tenant"]:
        params["tenant"] = scope["tenant"]
    if scope["workspace"]:
        params["workspace"] = scope["workspace"]
    if compare["metric"] != "(keep)":
        params["cmp_metric"] = compare["metric"]
    if compare["retriever"] != "(keep)":
        params["cmp_retriever"] = compare["retriever"]
    if compare["query"] != DEFAULT_QUERY:
        params["cmp_query"] = compare["query"]
    if evaluation["query"] != DEFAULT_QUERY:
        params["eval_query"] = evaluation["query"]
    if evaluation["evaluator"] != "(active)":
        params["eval_evaluator"] = evaluation["evaluator"]
    if evaluation["dataset_choice"] != "Built-in benchmark":
        params["eval_dataset_choice"] = evaluation["dataset_choice"]
    if evaluation["dataset_source"] != "Built-in benchmark":
        params["eval_dataset_source"] = evaluation["dataset_source"]
    if evaluation["dataset_evaluator"] != "(active)":
        params["eval_dataset_evaluator"] = evaluation["dataset_evaluator"]
    if evaluation["dataset_top_k"] != 3:
        params["eval_dataset_top_k"] = str(evaluation["dataset_top_k"])
    if evaluation["job_id"]:
        params["eval_job"] = evaluation["job_id"]
    if governance["time_range"] != "Last hour":
        params["gov_time"] = governance["time_range"]
    if governance["tenant"]:
        params["gov_tenant"] = governance["tenant"]
    if governance["app"]:
        params["gov_app"] = governance["app"]
    if governance["user"]:
        params["gov_user"] = governance["user"]
    if governance["request_id"]:
        params["gov_request"] = governance["request_id"]
    if audit["limit"] != 50:
        params["audit_limit"] = str(audit["limit"])
    if audit["event_type"]:
        params["audit_event"] = audit["event_type"]
    if audit["request_id"]:
        params["audit_request"] = audit["request_id"]
    if approvals["status"] != "pending":
        params["approval_status"] = approvals["status"]
    if normalized["screen"] == "Approvals" and approvals["request_id"]:
        params["approval_request"] = approvals["request_id"]
    if approvals["action"] != ANY_VALUE:
        params["approval_action"] = approvals["action"]
    if approvals["policy"] != ANY_VALUE:
        params["approval_policy"] = approvals["policy"]
    if approvals["requester"] != ANY_VALUE:
        params["approval_requester"] = approvals["requester"]
    if approvals["tenant"] != ANY_VALUE:
        params["approval_tenant"] = approvals["tenant"]
    if approvals["age"] != AGE_FILTER_OPTIONS[0]:
        params["approval_age"] = approvals["age"]
    if approvals["search"]:
        params["approval_search"] = approvals["search"]
    if approvals["sort"] != DEFAULT_SORT:
        params["approval_sort"] = approvals["sort"]
    if approvals["page"] != 1:
        params["approval_page"] = str(approvals["page"])
    if approvals["page_size"] != DEFAULT_PAGE_SIZE:
        params["approval_page_size"] = str(approvals["page_size"])
    if approvals["warning_hours"] != DEFAULT_SLA_WARNING_HOURS:
        params["approval_warning_hours"] = str(approvals["warning_hours"])
    if approvals["critical_hours"] != DEFAULT_SLA_CRITICAL_HOURS:
        params["approval_critical_hours"] = str(approvals["critical_hours"])
    return params


def merge_query_params(
    existing: Mapping[str, Any],
    workspace_params: Mapping[str, str],
) -> Dict[str, str]:
    """Preserve unknown embed params while replacing managed workspace keys."""
    preserved = {
        key: _first(value)
        for key, value in (existing or {}).items()
        if key not in MANAGED_PARAMS
    }
    preserved.update(workspace_params)
    return preserved


def _base_url_parts(base_url: str) -> Tuple[str, str, str]:
    value = (base_url or "").strip()
    if "://" not in value:
        value = f"http://{value or 'localhost:8501'}"
    parts = urlsplit(value)
    return parts.scheme or "http", parts.netloc or "localhost:8501", parts.path or "/"


def build_share_url(base_url: str, workspace: Mapping[str, Any]) -> str:
    """Build a share link, dropping bulky state until it fits the URL budget."""
    normalized = normalize_workspace(workspace)
    stripped = _strip_bulk(normalized)
    candidates = ((normalized, True), (stripped, True), (stripped, False))
    scheme, netloc, path = _base_url_parts(base_url)
    for candidate, include_blob in candidates:
        params = workspace_to_query_params(candidate, include_blob=include_blob)
        query = urlencode(params, quote_via=quote)
        url = urlunsplit((scheme, netloc, path, query, ""))
        if len(url) <= MAX_URL_CHARS:
            return url
    raise WorkspaceError("Workspace is too large to share in a URL")


def _strip_bulk(workspace: Mapping[str, Any]) -> Dict[str, Any]:
    stripped = normalize_workspace(workspace)
    stripped["saved_views"] = {kind: [] for kind in SAVED_VIEW_KINDS}
    stripped["saved_runs"] = []
    stripped["recent_runs"] = []
    stripped["evaluation"]["dataset_json"] = ""
    stripped["evaluation"]["response"] = ""
    stripped["evaluation"]["ground_truth"] = ""
    stripped["evaluation"]["datasets"] = []
    stripped["query_studio"]["query"] = stripped["query_studio"]["query"][:500]
    stripped["compare"]["query"] = stripped["compare"]["query"][:500]
    return stripped


def export_workspace(workspace: Mapping[str, Any]) -> str:
    """Export a normalized, redacted workspace as pretty JSON."""
    text = json.dumps(
        normalize_workspace(workspace),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    if len(text.encode("utf-8")) > MAX_EXPORT_BYTES:
        raise WorkspaceError("Workspace export is too large")
    return text


def import_workspace(text: str) -> Dict[str, Any]:
    """Import workspace JSON after size, shape and version validation."""
    if not isinstance(text, str) or not text.strip():
        raise WorkspaceError("Workspace file is empty")
    if len(text.encode("utf-8")) > MAX_EXPORT_BYTES:
        raise WorkspaceError("Workspace file is too large")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkspaceError("Workspace file is not valid JSON") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("Workspace file must contain an object")
    version = data.get("version", WORKSPACE_VERSION)
    if version != WORKSPACE_VERSION:
        raise WorkspaceError(f"Unsupported workspace version: {version}")
    return normalize_workspace(data)


def saved_view_names(workspace: Mapping[str, Any], kind: str) -> List[str]:
    """Return saved-view names for selectors, in newest-first order."""
    return [entry["name"] for entry in saved_views_for(workspace, kind)]
