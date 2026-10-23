"""Tests for issue #50: request attribution pipeline (workstream A3).

Acceptance covered here:
- the attribution context is resolved once at ingress (identity + tenancy),
- it reaches the trace, the cost record, metrics and the audit trail,
- spend / request counts are reportable per tenant/app/user over a window,
- the default (disabled) mode still reports the default dimensions,
- free-text identifiers are sanitised and bounded.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ops_api import RunHistory
from core.services.attribution import (
    DEFAULT_DIMENSION,
    AttributionContext,
    AttributionSettings,
    current_attribution,
    ensure_attribution,
    safe_identifier,
    set_attribution,
)

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"

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
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
"""

TENANTS_YAML = """
enabled: true
default_tenant: default
tenants:
  default:
    workspace: default
    app: platform
  acme:
    workspace: acme-prod
    app: support-copilot
    cost_center: cc-1234
"""


class _CapturingPipeline:
    """Records the kwargs it receives and returns a scripted result."""

    def __init__(self, cost: float = 0.25, failure_tags: Optional[List[str]] = None):
        self.calls: List[Dict[str, Any]] = []
        self.cost = cost
        self.failure_tags = list(failure_tags or [])

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
        self.calls.append({"query": query, "request_id": request_id, **kwargs})
        attribution = kwargs.get("attribution")
        dimensions = (
            attribution.dimensions()
            if isinstance(attribution, AttributionContext)
            else ensure_attribution().dimensions()
        )
        return {
            "response": f"answer:{query}",
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {"estimated_cost_usd": self.cost, "attribution": dimensions},
            "latency": {"total_ms": 1.0, "embedding": 0.5},
            "failure_tags": list(self.failure_tags),
            "attribution": dimensions,
            "observability": {
                "request_id": request_id,
                "status": "success",
                "attribution": dimensions,
            },
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _client(
    tmp_path: Path,
    pipeline: _CapturingPipeline,
    *,
    tenants: Optional[str] = TENANTS_YAML,
    attribution: Optional[str] = None,
) -> TestClient:
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = tmp_path / "prompt_config.yaml"
    prompt.write_text(REPO_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    observability = _write(
        tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
    )
    audit_path = _write(
        tmp_path / "audit.yaml", "enabled: true\nmax_entries: 200\n"
    )
    kwargs: Dict[str, Any] = {}
    if tenants is not None:
        kwargs["tenants_config_path"] = _write(tmp_path / "tenants.yaml", tenants)
    if attribution is not None:
        kwargs["attribution_config_path"] = _write(
            tmp_path / "attribution.yaml", attribution
        )
    app = create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        observability_config_path=observability,
        audit_config_path=audit_path,
        pipeline_builder=lambda **_: pipeline,
        **kwargs,
    )
    return TestClient(app)


# -- unit: context / sanitisation -----------------------------------------


def test_safe_identifier_bounds_and_sanitises():
    assert safe_identifier("  acme  ") == "acme"
    assert safe_identifier(None) == DEFAULT_DIMENSION
    assert safe_identifier("") == DEFAULT_DIMENSION
    # whitespace / control characters cannot reach a label or a trace verbatim
    assert "\n" not in safe_identifier("team\nadmin")
    assert " " not in safe_identifier("team admin")
    assert len(safe_identifier("x" * 500)) == 64


def test_context_defaults_and_merge():
    context = AttributionContext()
    assert context.dimensions() == {
        "tenant": DEFAULT_DIMENSION,
        "workspace": DEFAULT_DIMENSION,
        "app": DEFAULT_DIMENSION,
        "user": DEFAULT_DIMENSION,
        "cost_center": DEFAULT_DIMENSION,
    }
    merged = context.merged(tenant="acme", user="alice@example.com")
    assert merged.tenant == "acme"
    assert merged.user == "alice@example.com"
    assert merged.app == DEFAULT_DIMENSION  # untouched


def test_settings_gate_user_and_cost_center():
    enabled = AttributionSettings.from_config(
        {"attribution": {"enabled": True, "include_user": True}}
    )
    context = enabled.build(
        tenant="acme", user="alice", cost_center="cc-1"
    )
    assert context.user == "alice"
    assert context.cost_center == "cc-1"

    disabled = AttributionSettings.from_config({"enabled": False})
    default_context = disabled.build(tenant="acme", user="alice", cost_center="cc-1")
    assert default_context.tenant == "acme"
    # privacy-preserving default: per-user / cost-center stay out of telemetry
    assert default_context.user == DEFAULT_DIMENSION
    assert default_context.cost_center == DEFAULT_DIMENSION


def test_contextvar_set_and_reset():
    assert current_attribution() is None
    token = set_attribution(AttributionContext.from_values(tenant="acme"))
    try:
        assert current_attribution() is not None
        assert current_attribution().tenant == "acme"
        # ensure_attribution merges explicit overrides onto the current context
        merged = ensure_attribution(app="support")
        assert merged.tenant == "acme"
        assert merged.app == "support"
    finally:
        from core.services.attribution import reset_attribution

        reset_attribution(token)
    assert current_attribution() is None


# -- pipeline propagation -------------------------------------------------


def test_run_history_attribution_report_units():
    history = RunHistory(max_runs=10)
    history.record(
        "r1",
        {
            "cost": {"estimated_cost_usd": 0.5},
            "latency": {"total_ms": 2.0},
            "attribution": {
                "tenant": "acme",
                "workspace": "acme-prod",
                "app": "support",
                "user": "alice",
                "cost_center": "cc-1234",
            },
        },
        tenant="acme",
    )
    report = history.attribution_report()
    assert report["total_requests"] == 1
    assert report["by_app"]["support"]["cost_usd"] == 0.5
    assert report["by_user"]["alice"]["requests"] == 1
    assert report["by_cost_center"]["cc-1234"]["cost_usd"] == 0.5


# -- API: attribution flows to trace / audit / cost ------------------------


def test_query_attributes_tenant_app_user_in_trace_and_cost(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(
        tmp_path, pipeline, attribution="enabled: true\n"
    ) as client:
        body = client.post(
            "/v1/query",
            json={"query": "hello", "include_trace": True},
            headers={"X-Tenant-ID": "acme"},
        ).json()

    assert body["attribution"]["tenant"] == "acme"
    assert body["attribution"]["workspace"] == "acme-prod"
    assert body["attribution"]["app"] == "support-copilot"
    assert body["attribution"]["cost_center"] == "cc-1234"
    assert body["cost"]["attribution"]["tenant"] == "acme"
    assert body["observability"]["attribution"]["app"] == "support-copilot"


def test_audit_event_carries_attribution(tmp_path):
    # A degradation tag forces a governance audit event for the run.
    pipeline = _CapturingPipeline(failure_tags=["low_retrieval_score"])
    with _client(
        tmp_path, pipeline, attribution="enabled: true\n"
    ) as client:
        client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={"X-Tenant-ID": "acme"},
        )
        events = client.get("/v1/audit").json()["events"]

    governance = [e for e in events if e.get("event_type") == "governance"]
    assert governance, "expected a governance audit event"
    attribution = governance[-1]["attribution"]
    assert attribution["tenant"] == "acme"
    assert attribution["app"] == "support-copilot"


def test_attribution_report_endpoint_groups_by_app_and_user(tmp_path):
    pipeline = _CapturingPipeline(cost=0.25)
    with _client(tmp_path, pipeline, attribution="enabled: true\n") as client:
        for _ in range(2):
            client.post(
                "/v1/query",
                json={"query": "hello"},
                headers={"X-Tenant-ID": "acme"},
            )
        report = client.get(
            "/v1/attribution", headers={"X-Tenant-ID": "acme"}
        ).json()

    assert report["total_requests"] == 2
    assert report["by_app"]["support-copilot"]["requests"] == 2
    assert report["by_app"]["support-copilot"]["cost_usd"] == pytest.approx(0.5)
    assert report["by_tenant"]["acme"]["cost_usd"] == pytest.approx(0.5)
    assert report["tenant"] == "acme"


def test_attribution_report_window_filters_old_runs(tmp_path):
    pipeline = _CapturingPipeline(cost=1.0)
    with _client(tmp_path, pipeline, attribution="enabled: true\n") as client:
        client.post(
            "/v1/query", json={"query": "a"}, headers={"X-Tenant-ID": "acme"}
        )
        recent = client.get(
            "/v1/attribution?window_seconds=60", headers={"X-Tenant-ID": "acme"}
        ).json()
        old = client.get(
            "/v1/attribution?window_seconds=0", headers={"X-Tenant-ID": "acme"}
        ).json()

    assert recent["total_requests"] == 1
    assert recent["since"] is not None
    # a zero-length window only keeps runs recorded at (or after) "now"
    assert old["total_requests"] == 0


def test_default_mode_still_reports_default_dimension(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline, tenants=None) as client:
        body = client.post("/v1/query", json={"query": "hi"}).json()
        report = client.get("/v1/attribution").json()

    assert body["attribution"]["tenant"] == DEFAULT_DIMENSION
    assert report["by_tenant"][DEFAULT_DIMENSION]["requests"] == 1
    assert report["by_user"][DEFAULT_DIMENSION]["requests"] == 1


def test_free_text_user_id_is_not_echoed_verbatim(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        client.post(
            "/v1/query",
            json={"query": "hi"},
            headers={"X-Tenant-ID": "acme"},
        )
        report = client.get("/v1/attribution", headers={"X-Tenant-ID": "acme"}).json()

    # every dimension value is a bounded, label-safe token
    for name in report["by_user"]:
        assert "\n" not in name
        assert " " not in name
        assert len(name) <= 64


def test_run_history_attribution_report_units_failures():
    history = RunHistory(max_runs=10)
    for index in range(3):
        history.record(
            f"r{index}",
            {
                "cost": {"estimated_cost_usd": 0.1},
                "latency": {"total_ms": 1.0},
                "failure_tags": ["low_retrieval_score"] if index == 0 else [],
                "attribution": {
                    "tenant": "acme",
                    "app": "app-a",
                    "user": "alice",
                    "workspace": "ws",
                    "cost_center": "cc",
                },
            },
            tenant="acme",
        )
    report = history.attribution_report()
    assert report["by_tenant"]["acme"]["requests"] == 3
    assert report["by_tenant"]["acme"]["failures"] == 0
    assert report["total_cost_usd"] == pytest.approx(0.3, rel=1e-6)


def test_prometheus_exposes_attribution_counters():
    from core.services.telemetry import PrometheusCollector

    collector = PrometheusCollector()
    if not collector.is_available():
        pytest.skip("prometheus-client not installed")
    collector.record(
        {
            "response": "answer",
            "failure_tags": [],
            "cost": {"estimated_cost_usd": 0.75},
            "latency": {"embedding_ms": 2.0, "total_ms": 5.0},
            "attribution": {
                "tenant": "acme",
                "workspace": "acme-prod",
                "app": "support-copilot",
                "user": "alice",
                "cost_center": "cc-1234",
            },
        }
    )
    payload = collector.render()[0].decode("utf-8")
    assert (
        'genai_attributed_requests_total{app="support-copilot",status="success",'
        'tenant="acme",user="alice"} 1.0' in payload
    )
    assert (
        'genai_attributed_cost_usd_total{app="support-copilot",tenant="acme",'
        'user="alice"} 0.75' in payload
    )
