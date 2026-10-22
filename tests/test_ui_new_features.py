"""Console coverage for the post-v1 backend features (issue #82).

The Streamlit console is UI-only (Streamlit is not installed in CI), so the
screen contract is asserted structurally with :mod:`ast`, while the new
``ApiClient`` methods are exercised against the real FastAPI app over HTTP (the
``requests`` call is routed into a ``TestClient``).

Covers: the new Guardrails / Audit / Access screens being registered, the Query
Studio result panel surfacing cache/guardrail/redaction/expansion/resilience/OTel
data, the tour gaining steps for the new screens, and the client methods
``guardrails()``, ``audit()`` (with filters), ``access()`` and
``prometheus_metrics()``.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import pytest

from app.main import create_app

REPO_BASE = Path(__file__).resolve().parents[1]
UI_DIR = REPO_BASE / "ui"
APP_PATH = UI_DIR / "app.py"
TOUR_PATH = UI_DIR / "tour.py"
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"

NEW_SCREENS = ["Guardrails", "Audit", "Access / RBAC"]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _registered_screens() -> List[str]:
    """Keys of the module-level ``SCREENS`` dict in ``ui/app.py``."""
    for node in _tree(APP_PATH).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCREENS" for target in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            return [
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
    raise AssertionError("SCREENS dict literal not found in ui/app.py")


def _tour_screens() -> List[str]:
    screens: List[str] = []
    for node in ast.walk(_tree(TOUR_PATH)):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "screen" and isinstance(keyword.value, ast.Constant):
                    screens.append(keyword.value.value)
    return screens


def _function_source(name: str) -> str:
    text = APP_PATH.read_text(encoding="utf-8")
    for node in ast.walk(_tree(APP_PATH)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"function {name} not found in ui/app.py")


# -- structural contract ---------------------------------------------------


def test_app_registers_the_new_screens():
    screens = _registered_screens()
    for screen in NEW_SCREENS:
        assert screen in screens, f"missing screen {screen!r} in SCREENS"
    assert screens.index("Guardrails") > screens.index("Governance & Cost")
    assert screens.index("Traces") > screens.index("Access / RBAC")


def test_screens_consume_the_public_endpoints():
    text = APP_PATH.read_text(encoding="utf-8")
    assert "api.guardrails()" in text
    assert "api.audit(" in text
    assert "api.access()" in text
    assert "api.prometheus_metrics()" in text


def test_query_result_panel_surfaces_new_trace_data():
    source = _function_source("_render_query_result")
    for needle in (
        "cache_hit",
        "guardrails_enabled",
        "redaction_enabled",
        "expanded_queries",
        "guardrail_decisions",
        "resilience",
        "otel",
    ):
        assert needle in source, f"query result panel does not surface {needle!r}"


def test_tour_covers_the_new_screens():
    screens = _tour_screens()
    for screen in NEW_SCREENS:
        assert screen in screens, f"tour is missing a step for screen {screen!r}"


def test_ui_still_has_no_backend_imports():
    for path in sorted(UI_DIR.glob("*.py")):
        for node in ast.walk(_tree(path)):
            modules: List[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            offenders = [m for m in modules if m.split(".")[0] in ("app", "core")]
            assert not offenders, f"{path.name} imports backend modules {offenders}"


# -- client against the real API -----------------------------------------

MODELS_YAML = """
active_model: dummy
active_embedding_model: emb-a
models:
  dummy:
    provider: dummy
    context_window: 4096
embedding_models:
  emb-a:
    provider: dummy
    model_name: emb-a
"""

RETRIEVAL_YAML = """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: false
reranking:
  enabled: false
"""

GUARDRAILS_YAML = """
enabled: true
profile: standard
profiles:
  standard:
    input:
      - provider: injection
        sensitivity: medium
    output:
      - provider: deny_list
        terms: ["ignore previous instructions"]
        mask: "[REDACTED-POLICY]"
input: []
output: []
"""

AUDIT_YAML = """
enabled: true
path: ""
max_entries: 100
"""


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {
            "response": f"echo:{query}",
            "failure_tags": [],
            "retrieved_docs": ["doc-a"],
            "retrieved_docs_with_scores": [{"content": "doc-a", "score": 0.9, "metadata": {}}],
            "cost": {"estimated_cost_usd": 0.001},
            "latency": {"embedding": 1.0, "total_ms": 2.0},
            "cache_hit": False,
            "guardrail_decisions": [],
            "observability": {"status": "success", "guardrails_enabled": True},
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path) -> Dict[str, Any]:
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
        ),
        "guardrails_config_path": _write(tmp_path / "guardrails.yaml", GUARDRAILS_YAML),
        "audit_config_path": _write(tmp_path / "audit.yaml", AUDIT_YAML),
        "api_config_path": _write(
            tmp_path / "api.yaml", "require_api_key: false\napi_key: \"\"\nmax_batch_size: 5\n"
        ),
    }


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """ApiClient whose ``requests.request`` is routed into a TestClient."""
    pytest.importorskip("requests")
    from fastapi.testclient import TestClient

    import ui.client as client_module

    app = create_app(pipeline_builder=lambda **_ignored: _FakePipeline(), **_tmp_configs(tmp_path))
    test_client = TestClient(app)
    test_client.__enter__()

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        path = urlparse(url).path
        return test_client.request(method, path, headers=headers or {}, **kwargs)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    yield client_module.ApiClient(base_url="http://testserver")
    test_client.__exit__(None, None, None)


def test_client_guardrails_reports_profile_and_chains(api_client):
    result = api_client.guardrails()

    assert result.ok
    assert result.data["profile"] == "standard"
    assert result.data["enabled"] is True
    assert [g["provider"] for g in result.data["input"]] == ["injection"]
    assert [g["provider"] for g in result.data["output"]] == ["deny_list"]
    assert result.data["errors"] == []


def test_client_audit_returns_redacted_events(api_client):
    result = api_client.audit(limit=10)

    assert result.ok
    assert result.data["enabled"] is True
    assert result.data["count"] >= 1
    assert result.data["events"]
    assert "sk-" not in str(result.data)


def test_client_audit_filters_by_event_type(api_client):
    matching = api_client.audit(event_type="config")
    missing = api_client.audit(event_type="does-not-exist")

    assert matching.ok and missing.ok
    assert matching.data["count"] >= 1
    assert all(event["event_type"] == "config" for event in matching.data["events"])
    assert missing.data["count"] == 0


def test_client_access_reports_role_and_capabilities(api_client):
    result = api_client.access()

    assert result.ok
    assert result.data["role"] == "admin"
    assert "query" in result.data["capabilities"]
    assert "introspect" in result.data["capabilities"]


def test_client_prometheus_metrics_scrapes_or_reports_missing_extra(api_client):
    result = api_client.prometheus_metrics()

    if result.ok:
        assert "genai_requests_total" in result.data.get("raw", "")
    else:
        assert result.status_code == 503
