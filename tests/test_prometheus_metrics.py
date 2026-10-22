"""Tests for issue #44: Prometheus /metrics + dashboards/alerts pack.

Acceptance:
- GET /metrics returns valid Prometheus text exposition reflecting a real run,
- counters/histograms update after scripted runs (status, failure type, cost,
  cache, latency),
- the endpoint degrades to a 503 envelope when prometheus-client is absent,
- the shipped Grafana dashboards / Prometheus alerts parse as valid JSON/YAML
  and the compose profile references them.

``prometheus-client`` is an optional extra; when it is not installed the
exposition tests skip, but the fallback and packaging tests always run.
"""

import json
from collections import deque
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.telemetry import PrometheusCollector

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
DEPLOYMENT = REPO_BASE / "deployment"

prometheus_installed = PrometheusCollector().is_available()
requires_prometheus = pytest.mark.skipif(
    not prometheus_installed, reason="prometheus-client not installed"
)

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

OBSERVABILITY_YAML = """
log_level: INFO
redact_sensitive_data: true
"""


class _ScriptedPipeline:
    def __init__(self, results):
        self._results = deque(results)

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        if not self._results:
            raise AssertionError("scripted pipeline ran out of results")
        return self._results.popleft()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", OBSERVABILITY_YAML
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml", "enabled: true\nmax_cost_per_request_usd: 0.5\n"
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\n",
        ),
    }


def _success(
    cost=0.002,
    total_ms=35.0,
    embedding_ms=10.0,
    model="dummy",
    cache_hit=None,
    guardrail_decisions=None,
):
    return {
        "response": "answer",
        "failure_tags": [],
        "cache_hit": cache_hit,
        "cost": {"estimated_cost_usd": cost, "model": model},
        "latency": {
            "embedding": embedding_ms,
            "embedding_ms": embedding_ms,
            "retrieval_ms": 5.0,
            "total_ms": total_ms,
        },
        "guardrail_decisions": list(guardrail_decisions or []),
        "observability": {"status": "success"},
    }


def _decision(name, decision, stage="input", allowed=True):
    return {
        "guardrail": name,
        "stage": stage,
        "decision": decision,
        "allowed": allowed,
        "reason": None,
        "labels": [],
        "details": {},
    }


def _blocked(decisions, failed_stage="guardrail_input"):
    return {
        "response": None,
        "error": "blocked by guardrail",
        "failure_type": "guardrail_input_blocked",
        "failure_tags": ["guardrail_input_blocked"],
        "cost": {},
        "latency": {"embedding_ms": 3.0, "total_ms": 3.0},
        "guardrail_decisions": decisions,
        "observability": {"status": "failed", "failed_stage": failed_stage},
    }


def _failure():
    return {
        "response": None,
        "error": "llm exploded",
        "failure_type": "llm_failure",
        "failure_tags": ["llm_failure"],
        "cost": {},
        "latency": {"embedding_ms": 3.0, "total_ms": 3.0},
        "observability": {"status": "failed"},
    }


def _app(config_paths, results):
    scripted = _ScriptedPipeline(results)

    def builder(**_ignored):
        return scripted

    return create_app(pipeline_builder=builder, **config_paths)


def _run(client, request_id, query="hi"):
    return client.post(
        "/v1/query",
        json={"query": query, "include_trace": False},
        headers={"X-Request-ID": request_id},
    )


def _metrics_body(client) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    return response.text


# -- exposition -----------------------------------------------------------


@requires_prometheus
def test_metrics_endpoint_returns_valid_exposition(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        _run(client, "req-1")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    # HELP/TYPE headers and the series made it into the exposition.
    assert "# HELP genai_requests_total" in body
    assert "# TYPE genai_requests_total counter" in body
    assert 'genai_requests_total{status="success"}' in body


@requires_prometheus
def test_counters_reflect_success_and_failure(tmp_path):
    results = [_success(), _success(), _failure()]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        _run(client, "req-3")
        body = _metrics_body(client)

    assert 'genai_requests_total{status="success"} 2.0' in body
    assert 'genai_requests_total{status="failed"} 1.0' in body
    assert 'genai_failures_total{failure_type="llm_failure"} 1.0' in body
    assert 'genai_failure_tags_total{tag="llm_failure"} 1.0' in body


@requires_prometheus
def test_cost_counters_reflect_runs(tmp_path):
    results = [_success(cost=0.002, model="dummy"), _success(cost=0.003, model="dummy")]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        body = _metrics_body(client)

    assert "genai_cost_usd_total 0.005" in body
    assert 'genai_model_cost_usd_total{model="dummy"} 0.005' in body


@requires_prometheus
def test_latency_histogram_and_cache_and_inflight(tmp_path):
    results = [
        _success(total_ms=40.0, cache_hit=True),
        _success(total_ms=60.0, cache_hit=False),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        body = _metrics_body(client)

    assert "genai_stage_latency_ms_count" in body
    assert 'genai_stage_latency_ms_bucket{' in body
    assert 'stage="total"' in body
    assert 'genai_cache_events_total{event="hit"} 1.0' in body
    assert 'genai_cache_events_total{event="miss"} 1.0' in body
    assert "genai_in_flight_requests" in body


# -- collector unit --------------------------------------------------------


@requires_prometheus
def test_collector_records_without_http(tmp_path):
    collector = PrometheusCollector()
    collector.record(_success(cost=0.01, model="m1"))
    collector.record(_failure())
    payload, content_type = collector.render()
    body = payload.decode("utf-8")

    assert content_type.startswith("text/plain")
    assert 'genai_requests_total{status="success"} 1.0' in body
    assert 'genai_requests_total{status="failed"} 1.0' in body


# -- guardrail hit-rate metrics (issue #87) --------------------------------


@requires_prometheus
def test_guardrail_decision_counters_reflect_runs(tmp_path):
    results = [
        _success(guardrail_decisions=[_decision("noop", "allow")]),
        _success(guardrail_decisions=[_decision("pii", "redact")]),
        _blocked([_decision("injection", "block", allowed=False)]),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        _run(client, "req-3")
        body = _metrics_body(client)

    assert 'genai_guardrail_decisions_total{decision="allow",guardrail="noop"} 1.0' in body
    assert 'genai_guardrail_decisions_total{decision="redact",guardrail="pii"} 1.0' in body
    assert 'genai_guardrail_decisions_total{decision="block",guardrail="injection"} 1.0' in body
    assert 'genai_guardrail_blocks_total{guardrail="injection",stage="input"} 1.0' in body
    assert 'genai_failures_total{failure_type="guardrail_input_blocked"} 1.0' in body


@requires_prometheus
def test_guardrail_counters_ignore_cache_hits(tmp_path):
    decisions = [_decision("pii", "redact")]
    results = [
        _success(guardrail_decisions=decisions),
        _success(cache_hit=True, guardrail_decisions=decisions),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        body = _metrics_body(client)

    assert 'genai_guardrail_decisions_total{decision="redact",guardrail="pii"} 1.0' in body


@requires_prometheus
def test_guardrail_block_stage_falls_back_to_failed_stage(tmp_path):
    decision = _decision("deny_list", "block", allowed=False)
    decision.pop("stage")
    results = [_blocked([decision], failed_stage="guardrail_output")]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        body = _metrics_body(client)

    assert 'genai_guardrail_blocks_total{guardrail="deny_list",stage="output"} 1.0' in body


@requires_prometheus
def test_v1_metrics_exposes_guardrail_breakdown(tmp_path):
    results = [
        _success(guardrail_decisions=[_decision("noop", "allow")]),
        _success(guardrail_decisions=[_decision("pii", "redact")]),
        _blocked(
            [
                _decision("injection", "allow"),
                _decision("injection", "block", allowed=False),
            ]
        ),
        _success(cache_hit=True, guardrail_decisions=[_decision("pii", "redact")]),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        for index in range(len(results)):
            _run(client, f"req-{index}")
        payload = client.get("/v1/metrics").json()

    guardrails = payload["guardrails"]
    assert guardrails["by_guardrail"] == {
        "injection": {"allow": 1, "redact": 0, "block": 1},
        "noop": {"allow": 1, "redact": 0, "block": 0},
        "pii": {"allow": 0, "redact": 1, "block": 0},
    }
    assert guardrails["by_decision"] == {"allow": 2, "redact": 1, "block": 1}
    assert guardrails["total_decisions"] == 4
    assert guardrails["total_blocks"] == 1


def test_collector_degrades_when_library_absent(monkeypatch):
    # Simulate the optional dependency being missing: the collector reports
    # unavailable and render() raises instead of crashing at import.
    import core.services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_PROMETHEUS_AVAILABLE", False)
    collector = telemetry.PrometheusCollector()
    assert collector.is_available() is False
    collector.record(_success())  # no-op
    with pytest.raises(RuntimeError):
        collector.render()


def test_metrics_endpoint_503_when_library_absent(tmp_path, monkeypatch):
    import core.services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_PROMETHEUS_AVAILABLE", False)
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        response = client.get("/metrics")

    assert response.status_code == 503
    body = response.json()
    assert body["failure_type"] == "not_ready"
    assert "prometheus_not_installed" in body["failure_tags"]


# -- packaging / dashboards -----------------------------------------------


def test_grafana_dashboards_are_valid_json():
    dashboards = list((DEPLOYMENT / "observability" / "grafana" / "dashboards").glob("*.json"))
    assert dashboards, "no Grafana dashboards shipped"
    for path in dashboards:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["title"]
        assert data["panels"], f"{path.name} has no panels"


def test_prometheus_alerts_and_config_are_valid_yaml():
    prom_dir = DEPLOYMENT / "observability" / "prometheus"
    alerts = yaml.safe_load((prom_dir / "alerts.yml").read_text(encoding="utf-8"))
    rules = alerts["groups"][0]["rules"]
    assert len(rules) >= 3
    for rule in rules:
        assert rule["alert"]
        assert rule["expr"]

    scrape = yaml.safe_load((prom_dir / "prometheus.yml").read_text(encoding="utf-8"))
    assert any(
        cfg["metrics_path"] == "/metrics" for cfg in scrape["scrape_configs"]
    )


def test_grafana_dashboard_has_guardrail_panels():
    dashboard = DEPLOYMENT / "observability" / "grafana" / "dashboards" / "genai-overview.json"
    data = json.loads(dashboard.read_text(encoding="utf-8"))
    exprs = [
        target.get("expr", "")
        for panel in data["panels"]
        for target in panel.get("targets", [])
    ]
    assert any("genai_guardrail_decisions_total" in expr for expr in exprs)
    assert any("genai_guardrail_blocks_total" in expr for expr in exprs)
    assert any("redact|block" in expr for expr in exprs), "no guardrail hit-rate panel"
    titles = [panel.get("title", "") for panel in data["panels"]]
    assert any("Guardrail" in title for title in titles)


def test_prometheus_has_guardrail_block_alert():
    prom_dir = DEPLOYMENT / "observability" / "prometheus"
    alerts = yaml.safe_load((prom_dir / "alerts.yml").read_text(encoding="utf-8"))
    rules = alerts["groups"][0]["rules"]
    rule = next(r for r in rules if r["alert"] == "GuardrailBlockRateHigh")
    assert "genai_guardrail_decisions_total" in rule["expr"]
    assert 'decision="block"' in rule["expr"]


def test_compose_profile_references_observability_assets():
    compose = yaml.safe_load((DEPLOYMENT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "prometheus" in services and "grafana" in services
    assert "observability" in services["prometheus"]["profiles"]

    prometheus_volumes = " ".join(services["prometheus"]["volumes"])
    grafana_volumes = " ".join(services["grafana"]["volumes"])
    assert "alerts.yml" in prometheus_volumes
    assert "dashboards" in grafana_volumes


def test_observability_extra_declared_in_pyproject():
    pyproject = (REPO_BASE / "pyproject.toml").read_text(encoding="utf-8")
    assert "observability = [" in pyproject
    assert "prometheus-client" in pyproject
    requirements = (REPO_BASE / "requirements-observability.txt").read_text(encoding="utf-8")
    assert "prometheus-client" in requirements
