"""Tests for issue #48: tenant / workspace model (workstream A1).

Acceptance covered here:
- requests resolve to a tenant (header, API-key mapping, default),
- unknown explicit tenants are rejected,
- cache/spend/trace/audit attribution is per tenant,
- tenant overlays change a request-scoped limit without touching global config,
- the default (disabled) mode keeps legacy behavior.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ops_api import RunHistory
from core.services.audit_log import AuditLogger
from core.services.tenancy import TenantResolver, UnknownTenantError

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
    budget_cap_usd: 5.0
    top_k_max: 3
    allowed_models: [local-qwen]
    overrides:
      retrieval:
        top_k: 2
  beta:
    workspace: beta-dev
    app: beta-app
api_keys:
  acme-key: acme
"""


class _CapturingPipeline:
    """Pipeline test double that records the kwargs and returns a scripted result."""

    def __init__(self, cost: float = 0.01):
        self.calls: List[Dict[str, Any]] = []
        self.cost = cost

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "request_id": request_id,
                **kwargs,
            }
        )
        result = {
            "response": f"answer:{query}",
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {"estimated_cost_usd": self.cost},
            "latency": {"total_ms": 1.0, "embedding": 0.5},
            "failure_tags": [],
            "observability": {
                "request_id": request_id,
                "status": "success",
            },
        }
        if kwargs.get("tenant") is not None:
            result.update(
                tenant=kwargs["tenant"],
                workspace=kwargs.get("workspace"),
                app=kwargs.get("app"),
            )
            result["observability"]["tenant"] = kwargs["tenant"]
        return result


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _configs(tmp_path: Path, *, tenants: Optional[str] = TENANTS_YAML, audit: bool = True):
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = tmp_path / "prompt_config.yaml"
    prompt.write_text(REPO_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    observability = _write(
        tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
    )
    audit_path = _write(
        tmp_path / "audit.yaml",
        f"enabled: {'true' if audit else 'false'}\nmax_entries: 100\n",
    )
    tenants_path = _write(tmp_path / "tenants.yaml", tenants) if tenants else None
    return models, retrieval, prompt, observability, audit_path, tenants_path


def _client(tmp_path: Path, pipeline: _CapturingPipeline, **cfg_overrides):
    models, retrieval, prompt, observability, audit_path, tenants_path = _configs(
        tmp_path, **cfg_overrides
    )
    kwargs: Dict[str, Any] = {}
    if tenants_path is not None:
        kwargs["tenants_config_path"] = tenants_path
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


# -- resolver unit tests -------------------------------------------------


def test_disabled_resolver_is_implicit_default():
    resolver = TenantResolver.from_config(
        {"enabled": False, "tenants": {"acme": {"workspace": "acme-prod"}}}
    )
    tenant = resolver.resolve(tenant_header="acme")
    assert tenant.id == "default"
    assert tenant.workspace == "default"


def test_enabled_resolver_header_and_api_key_precedence():
    resolver = TenantResolver.from_config(
        {
            "enabled": True,
            "default_tenant": "default",
            "tenants": {
                "default": {},
                "acme": {"workspace": "acme-prod", "app": "support"},
                "beta": {"workspace": "beta-dev"},
            },
            "api_keys": {"acme-key": "acme"},
        }
    )
    assert resolver.resolve(tenant_header="acme").workspace == "acme-prod"
    assert resolver.resolve(api_key="acme-key").id == "acme"
    assert resolver.resolve(tenant_header="beta", api_key="acme-key").id == "beta"
    assert resolver.resolve().id == "default"


def test_unknown_tenant_raises():
    resolver = TenantResolver.from_config(
        {"enabled": True, "tenants": {"default": {}}}
    )
    with pytest.raises(UnknownTenantError):
        resolver.resolve(tenant_header="ghost")
    mapped = TenantResolver(
        enabled=True, tenants={"default": {}}, api_keys={"k": "missing"}
    )
    with pytest.raises(UnknownTenantError):
        mapped.resolve(api_key="k")


def test_overlay_precedence_and_fallback():
    resolver = TenantResolver.from_config(
        {
            "enabled": True,
            "tenants": {
                "acme": {"overrides": {"retrieval": {"top_k": 2}, "governance": {}}}
            },
        }
    )
    merged = resolver.apply_overlay(
        "retrieval", {"top_k": 5, "similarity_metric": "cosine"}, "acme"
    )
    assert merged == {"top_k": 2, "similarity_metric": "cosine"}
    untouched = resolver.apply_overlay("retrieval", {"top_k": 5}, "other")
    assert untouched == {"top_k": 5}


# -- API attribution / isolation -----------------------------------------


def test_query_attributes_tenant_in_result_trace_and_history(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        response = client.post(
            "/v1/query",
            json={"query": "hello", "include_trace": True},
            headers={"X-Tenant-ID": "acme"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tenant"] == "acme"
        assert body["workspace"] == "acme-prod"
        assert body["app"] == "support-copilot"
        trace_id = body["request_id"]
        assert body["observability"]["tenant"] == "acme"

        trace = client.get(
            f"/v1/traces/{trace_id}", headers={"X-Tenant-ID": "acme"}
        ).json()
        assert trace["tenant"] == "acme"

        history = client.app.state.history
        assert history.spend_window("acme")["requests"] == 1
        assert history.spend_window("beta")["requests"] == 0


def test_top_k_uses_tenant_overlay_and_cap(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        client.post("/v1/query", json={"query": "q"}, headers={"X-Tenant-ID": "acme"})
        assert pipeline.calls[-1]["top_k"] == 2  # overlay beats global top_k=3

        client.post(
            "/v1/query",
            json={"query": "q", "top_k": 10},
            headers={"X-Tenant-ID": "acme"},
        )
        assert pipeline.calls[-1]["top_k"] == 3  # tenant cap clamps explicit 10


def test_unknown_tenant_header_is_400(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        response = client.post(
            "/v1/query", json={"query": "q"}, headers={"X-Tenant-ID": "ghost"}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["failure_type"] == "unknown_tenant"
        assert pipeline.calls == []


def test_budget_cap_returns_402(tmp_path):
    pipeline = _CapturingPipeline(cost=10.0)
    with _client(tmp_path, pipeline) as client:
        first = client.post(
            "/v1/query", json={"query": "q"}, headers={"X-Tenant-ID": "acme"}
        )
        assert first.status_code == 200
        second = client.post(
            "/v1/query", json={"query": "q2"}, headers={"X-Tenant-ID": "acme"}
        )
        assert second.status_code == 402
        body = second.json()
        assert body["failure_type"] == "cost_limit_exceeded"
        assert "tenant_budget_exceeded" in body["failure_tags"]
        assert body["tenant"] == "acme"
        # Another tenant is unaffected by acme's cap.
        other = client.post(
            "/v1/query", json={"query": "q3"}, headers={"X-Tenant-ID": "beta"}
        )
        assert other.status_code == 200


def test_ops_reads_are_scoped_to_caller_tenant(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        acme = client.post(
            "/v1/query", json={"query": "acme-q"}, headers={"X-Tenant-ID": "acme"}
        ).json()
        client.post("/v1/query", json={"query": "beta-q"}, headers={"X-Tenant-ID": "beta"})

        metrics = client.get("/v1/metrics", headers={"X-Tenant-ID": "acme"}).json()
        assert metrics["total_runs"] == 1
        assert metrics["tenant"] == "acme"

        foreign = client.get(
            f"/v1/traces/{acme['request_id']}", headers={"X-Tenant-ID": "beta"}
        )
        assert foreign.status_code == 404

        forbidden = client.get(
            "/v1/metrics?tenant=beta", headers={"X-Tenant-ID": "acme"}
        )
        assert forbidden.status_code == 403


def test_tenants_endpoint_and_config_introspection(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        response = client.get("/v1/tenants", headers={"X-Tenant-ID": "acme"})
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["default_tenant"] == "default"
        assert body["current"]["id"] == "acme"
        assert {item["id"] for item in body["tenants"]} == {"default", "acme", "beta"}

        config = client.get("/v1/config").json()["config"]
        assert config["tenants"]["tenants"]["acme"]["workspace"] == "acme-prod"


def test_audit_events_carry_tenant_and_filter(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        client.post("/v1/query", json={"query": "q"}, headers={"X-Tenant-ID": "acme"})
        events = client.get("/v1/audit?tenant=acme").json()["events"]
        assert events == []  # successful, governance-neutral query -> no decision event

        # A budget denial is a governance decision and is attributed.
        pipeline.cost = 10.0
        client.post("/v1/query", json={"query": "q1"}, headers={"X-Tenant-ID": "acme"})
        client.post("/v1/query", json={"query": "q2"}, headers={"X-Tenant-ID": "acme"})
        denied = client.get("/v1/audit?tenant=acme").json()["events"]
        assert denied and all(event["tenant"] == "acme" for event in denied)
        assert client.get("/v1/audit?tenant=beta").json()["events"] == []


def test_default_mode_is_unchanged(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline, tenants=None) as client:
        response = client.post("/v1/query", json={"query": "q"})
        assert response.status_code == 200
        body = response.json()
        assert "tenant" not in body
        assert pipeline.calls[-1] == {
            "query": "q",
            "top_k": None,
            "request_id": body["request_id"],
        }


def test_audit_logger_tenant_field_is_optional_and_filterable():
    logger = AuditLogger(enabled=True)
    event = logger.record("governance", "cost_check", "denied")
    assert event is not None and event["tenant"] is None
    logger.record("governance", "cost_check", "denied", tenant="acme")
    assert len(logger.events(tenant="acme")) == 1
    assert len(logger.events()) == 2


def test_experiments_are_tenant_scoped(tmp_path):
    pipeline = _CapturingPipeline()
    with _client(tmp_path, pipeline) as client:
        launch = client.post(
            "/v1/experiments",
            json={"kind": "single", "query": "q", "docs": ["alpha doc", "beta doc"]},
            headers={"X-Tenant-ID": "acme"},
        )
        assert launch.status_code == 202, launch.text
        exp = launch.json()
        assert exp["tenant"] == "acme"

        own = client.get(
            f"/v1/experiments/{exp['id']}", headers={"X-Tenant-ID": "acme"}
        )
        assert own.status_code == 200
        assert own.json()["tenant"] == "acme"

        foreign = client.get(
            f"/v1/experiments/{exp['id']}", headers={"X-Tenant-ID": "beta"}
        )
        assert foreign.status_code == 404


def test_run_history_isolation_unit():
    history = RunHistory(max_runs=10, max_traces=10)
    history.record("r1", {"cost": {"estimated_cost_usd": 1.0}, "observability": {"tenant": "a"}}, tenant="a")
    history.record("r2", {"cost": {"estimated_cost_usd": 2.0}, "observability": {"tenant": "b"}}, tenant="b")
    assert history.spend_window("a")["total_cost_usd"] == 1.0
    assert history.spend_window("b")["total_cost_usd"] == 2.0
    assert history.spend_window()["requests"] == 2
    assert history.metrics("a")["total_runs"] == 1
    assert history.trace("r1", tenant="b") is None
    assert history.trace("r1", tenant="a")["tenant"] == "a"
