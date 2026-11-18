"""Cross-cutting guards for the UI look/feel rollout (#240-#257, #265).

Streamlit is not installed in CI, so the console contract is checked
structurally. These guards keep the plan-to-tracker map, HTTP-only rule,
public API paths, typed schemas and redaction/tenant-scope contracts aligned
while bot-win lands the UI slices.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

REPO_BASE = Path(__file__).resolve().parents[1]
UI_DIR = REPO_BASE / "ui"
PLAN_PATH = REPO_BASE / "docs" / "ui-enterprise-look-and-feel-plan.md"
SPLIT_PATH = REPO_BASE / "docs" / "bot-work-split.md"
CLIENT_PATH = UI_DIR / "client.py"
APP_PATH = UI_DIR / "app.py"
SCHEMA_PATH = REPO_BASE / "app" / "schemas.py"
CONTRACT_TEST_PATH = REPO_BASE / "tests" / "test_api_contract.py"
TENANT_SCOPE_TEST_PATHS = (
    REPO_BASE / "tests" / "test_tenancy.py",
    REPO_BASE / "tests" / "test_tenant_header_binding.py",
    REPO_BASE / "tests" / "test_identity.py",
    REPO_BASE / "tests" / "test_approvals_queue.py",
)

PLAN_ISSUES = set(range(240, 258)) | {265}

REQUIRED_PLAN_AREAS = {
    "### P0 — App shell & branding",
    "### P0 — Component patterns (reusable, pure where possible)",
    "### P1 — Replace raw payloads with structured views",
    "### P1 — Visualization upgrades",
    "### P2 — Responsiveness & density parity",
    "### P3 — Trust, copy, and micro-polish",
}

REQUIRED_SCREEN_FUNCTIONS = {
    "Overview / Health": "screen_overview",
    "Query Studio": "screen_query_studio",
    "Compare (what-if)": "screen_compare",
    "Evaluation": "screen_evaluation",
    "Governance & Cost": "screen_governance",
    "Guardrails": "screen_guardrails",
    "Approvals": "screen_approvals",
    "Audit": "screen_audit",
    "Access / RBAC": "screen_access",
    "Admin": "screen_admin",
    "Traces": "screen_traces",
    "Settings (read-only)": "screen_settings",
    "Feedback": "screen_feedback",
}

REQUIRED_CLIENT_METHODS = {
    "health",
    "ready",
    "models",
    "embedding_models",
    "retrievers",
    "rerankers",
    "evaluators",
    "guardrails",
    "access",
    "effective_config",
    "query",
    "batch_query",
    "evaluate",
    "launch_experiment",
    "get_experiment",
    "rebuild",
    "governance_status",
    "trace",
    "metrics",
    "audit",
    "approvals",
    "approval",
    "decide_approval",
    "admin_list_tenants",
    "admin_update_tenant",
    "admin_list_users",
    "prometheus_metrics",
}

REQUIRED_CLIENT_PATHS = {
    "/health",
    "/ready",
    "/v1/config",
    "/v1/guardrails",
    "/v1/access",
    "/v1/query",
    "/v1/query:batch",
    "/v1/audit",
    "/v1/approvals",
    "/v1/traces/{}",
    "/v1/metrics",
    "/metrics",
}

REQUIRED_SCHEMAS = {
    "ModelsResponse",
    "EmbeddingModelsResponse",
    "RetrieversResponse",
    "RerankersResponse",
    "EvaluatorsResponse",
    "GuardrailsResponse",
    "EffectiveConfigResponse",
    "EvaluateResponse",
    "ExperimentLaunchResponse",
    "ExperimentStatusResponse",
    "RebuildResponse",
    "GovernanceStatusResponse",
    "MetricsResponse",
    "AuditEventsResponse",
    "ApprovalListResponse",
    "ApprovalRequestResponse",
    "TenantsResponse",
    "AccessResponse",
    "AdminTenantListResponse",
    "AdminUserListResponse",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _path_pattern(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{}")
        return "".join(parts)
    raise AssertionError("unsupported API path expression in ui/client.py")


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _api_client_methods() -> Dict[str, List[str]]:
    methods: Dict[str, List[str]] = {}
    for node in _tree(CLIENT_PATH).body:
        if not isinstance(node, ast.ClassDef) or node.name != "ApiClient":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            endpoints: List[str] = []
            for call in ast.walk(item):
                if not isinstance(call, ast.Call):
                    continue
                if not isinstance(call.func, ast.Attribute):
                    continue
                if call.func.attr not in {"get", "post"}:
                    continue
                if not isinstance(call.func.value, ast.Name) or call.func.value.id != "self":
                    continue
                if call.args:
                    endpoints.append(_path_pattern(call.args[0]))
            methods[item.name] = endpoints
    assert methods, "ApiClient class or methods not found"
    return methods


def _expected_paths() -> Set[str]:
    for node in _tree(CONTRACT_TEST_PATH).body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "EXPECTED_PATHS" not in names:
            continue
        assert isinstance(node.value, ast.Set)
        return {
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    raise AssertionError("EXPECTED_PATHS not found in test_api_contract.py")


def _registered_screens() -> Set[str]:
    for node in _tree(APP_PATH).body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "SCREENS" not in names:
            continue
        assert isinstance(node.value, ast.Dict)
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError("SCREENS dict literal not found in ui/app.py")


def _defined_screen_functions() -> Set[str]:
    return {
        node.name
        for node in _tree(APP_PATH).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("screen_")
    }


def _schema_classes() -> Set[str]:
    return {
        node.name
        for node in _tree(SCHEMA_PATH).body
        if isinstance(node, ast.ClassDef)
    }


def _plan_redistribution_issues() -> Set[str]:
    text = SPLIT_PATH.read_text(encoding="utf-8")
    section = text.split("## UI look/feel redistribution", 1)[1].split("\n## ", 1)[0]
    issues: Set[int] = set()
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        for start, end in re.findall(r"(?<!PR )#(\d+)(?:-#(\d+))?", line):
            first = int(start)
            last = int(end) if end else first
            issues.update(range(first, last + 1))
    return issues


def test_plan_tracker_map_covers_every_ui_look_feel_issue():
    assert _plan_redistribution_issues() == PLAN_ISSUES


def test_redistribution_doc_states_the_ownership_boundary():
    section = SPLIT_PATH.read_text(encoding="utf-8").split(
        "## UI look/feel redistribution", 1
    )[1]
    assert "#265" in section and "bot-uni" in section
    assert "never `ui/`" in section
    split_text = SPLIT_PATH.read_text(encoding="utf-8")
    assert "bot-win implements #240-#257; bot-uni handles #265 only" in split_text
    assert "Bot-uni must not edit `ui/*.py` for this tranche" in split_text


def test_plan_doc_retains_all_global_and_screen_areas():
    text = PLAN_PATH.read_text(encoding="utf-8")
    for area in REQUIRED_PLAN_AREAS:
        assert area in text, f"plan doc no longer defines {area!r}"
    for screen, function in REQUIRED_SCREEN_FUNCTIONS.items():
        assert screen in text, f"plan doc no longer covers screen {screen!r}"
        assert function in text, f"plan doc no longer names {function!r}"


def test_plan_screen_functions_are_registered():
    screens = _registered_screens()
    functions = _defined_screen_functions()
    for screen, function in REQUIRED_SCREEN_FUNCTIONS.items():
        assert screen in screens, f"missing registered screen {screen!r}"
        assert function in functions, f"missing screen function {function!r}"


def test_ui_files_stay_http_only_during_look_feel_rollout():
    for path in sorted(UI_DIR.glob("*.py")):
        for node in ast.walk(_tree(path)):
            modules: List[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            offenders = [module for module in modules if module.split(".")[0] in {"app", "core"}]
            assert not offenders, f"{path.name} imports backend modules {offenders}"


def test_api_client_exposes_all_plan_endpoints():
    methods = set(_api_client_methods())
    missing = REQUIRED_CLIENT_METHODS - methods
    assert not missing, f"ApiClient is missing methods {sorted(missing)}"


def test_api_client_paths_match_the_public_contract():
    paths = {_normalize(path) for endpoints in _api_client_methods().values() for path in endpoints}
    expected = {_normalize(path) for path in _expected_paths()}
    extra = paths - expected
    assert not extra, f"ApiClient paths not in API contract: {sorted(extra)}"
    missing = REQUIRED_CLIENT_PATHS - paths
    assert not missing, f"ApiClient is missing plan paths {sorted(missing)}"


def test_screens_only_call_declared_client_methods():
    methods = set(_api_client_methods())
    used = {
        node.func.attr
        for node in ast.walk(_tree(APP_PATH))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "api"
    }
    unknown = used - methods
    assert not unknown, f"screens call undeclared ApiClient methods {sorted(unknown)}"


def test_typed_schemas_exist_for_plan_endpoints():
    missing = REQUIRED_SCHEMAS - _schema_classes()
    assert not missing, f"response schemas missing from app/schemas.py: {sorted(missing)}"


def test_redaction_and_tenant_scope_contract_guards_are_present():
    contract_text = CONTRACT_TEST_PATH.read_text(encoding="utf-8")
    assert "def test_config_and_trace_never_leak_secrets" in contract_text
    assert '"/v1/config"' in contract_text
    assert '"/v1/traces/{request_id}"' in contract_text
    scope_text = "\n".join(path.read_text(encoding="utf-8") for path in TENANT_SCOPE_TEST_PATHS)
    assert "forbidden_tenant_scope" in scope_text
