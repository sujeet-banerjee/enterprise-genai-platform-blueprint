"""Tests for issue #38: governance status, trace lookup and metrics endpoints.

Acceptance:
- /v1/governance/status reflects the governance config (and reports disabled
  when ``governance.enabled=false`` while counters keep accumulating),
- /v1/traces/{request_id} returns the same redacted payload the logs emit and
  404s on a miss,
- /v1/metrics aggregates latency / failure / cost across a scripted mix of
  successful and failed runs,
- the underlying stores are bounded (oldest evicted first).
"""

from collections import deque
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.ops_api import RunHistory

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


def _tmp_configs(
    tmp_path: Path,
    *,
    governance_enabled: bool = True,
    history_max_runs: int = 1000,
    trace_store_max: int = 500,
):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", OBSERVABILITY_YAML
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml",
            f"""
enabled: {"true" if governance_enabled else "false"}
max_cost_per_request_usd: 0.5
safety_margin_tokens: 128
avg_chunk_tokens: 300
""",
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            f"""
require_api_key: false
api_key: ""
allow_rebuild: false
history_max_runs: {history_max_runs}
trace_store_max: {trace_store_max}
""",
        ),
    }


def _success(cost=0.002, embedding_ms=10.0, total_ms=35.0, secret="sk-live-secret"):
    return {
        "response": "answer",
        "failure_tags": [],
        "cost": {
            "estimated_cost_usd": cost,
            "model": "dummy",
            "input_tokens": 10,
            "output_tokens": 5,
        },
        "latency": {
            "embedding": embedding_ms,
            "retrieval": 5.0,
            "llm_generation": 20.0,
            "embedding_ms": embedding_ms,
            "total_ms": total_ms,
        },
        "observability": {
            "status": "success",
            "query": "what is rag",
            "api_key": secret,
            "nested": {"access_token": secret},
        },
    }


def _failure(embedding_ms=3.0):
    return {
        "response": None,
        "error": "llm exploded",
        "failure_type": "llm_failure",
        "failure_tags": ["llm_failure"],
        "cost": {},
        "latency": {"embedding": embedding_ms, "total_ms": embedding_ms},
        "observability": {
            "status": "failed",
            "failed_stage": "llm_generation",
            "failure_tags": ["llm_failure"],
        },
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


# -- governance status ----------------------------------------------------


def test_governance_status_reflects_config(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        body = client.get("/v1/governance/status").json()

    assert body["enabled"] is True
    assert body["max_cost_per_request_usd"] == 0.5
    assert body["safety_margin_tokens"] == 128
    assert body["avg_chunk_tokens"] == 300
    assert body["window"]["requests"] == 0
    assert body["window"]["total_cost_usd"] == 0.0
    assert body["request_id"]


def test_governance_disabled_but_still_accumulates(tmp_path):
    config_paths = _tmp_configs(tmp_path, governance_enabled=False)
    with TestClient(_app(config_paths, [_success(cost=0.004)])) as client:
        _run(client, "req-1")
        status = client.get("/v1/governance/status").json()

        assert status["enabled"] is False
        assert status["window"]["requests"] == 1
        assert status["window"]["total_cost_usd"] == 0.004


def test_spend_window_sums_recent_costs(tmp_path):
    with TestClient(
        _app(_tmp_configs(tmp_path), [_success(cost=0.001), _success(cost=0.003)])
    ) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        window = client.get("/v1/governance/status").json()["window"]

    assert window["requests"] == 2
    assert window["total_cost_usd"] == 0.004
    assert window["mean_cost_usd"] == 0.002


# -- metrics --------------------------------------------------------------


def test_metrics_reflects_scripted_mixed_runs(tmp_path):
    results = [
        _success(cost=0.002),
        _success(cost=0.004),
        _failure(),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _run(client, "req-1")
        _run(client, "req-2")
        _run(client, "req-3")
        body = client.get("/v1/metrics").json()

    assert body["total_runs"] == 3
    assert body["success_count"] == 2
    assert body["failure_count"] == 1
    assert body["failure_rate"] == round(1 / 3, 6)
    assert body["failures_by_type"] == {"llm_failure": 1}
    assert body["failures_by_tag"] == {"llm_failure": 1}
    assert body["cost"]["total_cost_usd"] == 0.006
    assert body["cost"]["priced_runs"] == 2
    assert body["latency_ms"]["embedding"]["count"] == 3
    assert body["total_latency_ms"]["count"] == 3


def test_metrics_latency_percentiles(tmp_path):
    results = [
        _success(embedding_ms=10.0, total_ms=100.0),
        _success(embedding_ms=20.0, total_ms=200.0),
        _success(embedding_ms=30.0, total_ms=300.0),
    ]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        for index in range(3):
            _run(client, f"req-{index}")
        body = client.get("/v1/metrics").json()

    embedding = body["latency_ms"]["embedding"]
    assert embedding["mean"] == 20.0
    assert embedding["p50"] == 20.0
    assert embedding["p95"] == 30.0
    assert body["total_latency_ms"]["p95"] == 300.0


# -- trace lookup ---------------------------------------------------------


def test_trace_lookup_returns_redacted_payload(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        _run(client, "trace-me")
        response = client.get("/v1/traces/trace-me")

    assert response.status_code == 200
    trace = response.json()
    assert trace["status"] == "success"
    assert trace["query"] == "what is rag"
    assert trace["api_key"] == "[REDACTED]"
    assert trace["nested"]["access_token"] == "[REDACTED]"
    assert "sk-live-secret" not in response.text


def test_trace_lookup_miss_returns_404_envelope(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        response = client.get("/v1/traces/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["failure_type"] == "unknown_failure"
    assert "trace_not_found" in body["failure_tags"]
    assert body["request_id"]


# -- store bounds ---------------------------------------------------------


def test_run_store_is_bounded(tmp_path):
    config_paths = _tmp_configs(tmp_path, history_max_runs=2)
    results = [_success(), _success(), _success()]
    with TestClient(_app(config_paths, results)) as client:
        for index in range(3):
            _run(client, f"req-{index}")
        body = client.get("/v1/metrics").json()

    assert body["total_runs"] == 2


def test_trace_store_is_bounded_lru(tmp_path):
    config_paths = _tmp_configs(tmp_path, trace_store_max=2)
    results = [_success(), _success(), _success()]
    with TestClient(_app(config_paths, results)) as client:
        for index in range(3):
            _run(client, f"req-{index}")
        assert client.get("/v1/traces/req-0").status_code == 404
        assert client.get("/v1/traces/req-1").status_code == 200
        assert client.get("/v1/traces/req-2").status_code == 200


# -- readiness / unit ------------------------------------------------------


def test_ops_endpoints_503_without_lifespan(tmp_path):
    client = TestClient(_app(_tmp_configs(tmp_path), []))
    metrics = client.get("/v1/metrics")
    status = client.get("/v1/governance/status")
    trace = client.get("/v1/traces/anything")

    for response in (metrics, status, trace):
        assert response.status_code == 503
        assert response.json()["failure_type"] == "not_ready"


def test_run_history_unit_bounds_and_redaction():
    history = RunHistory(max_runs=2, max_traces=1)
    history.record("a", _success(secret="sk-secret-a"))
    history.record("b", _success(secret="sk-secret-b"))
    history.record("c", _success(secret="sk-secret-c"))

    assert history.run_count() == 2
    assert history.trace_count() == 1
    assert history.trace("a") is None
    assert history.trace("c")["api_key"] == "[REDACTED]"

    metrics = history.metrics()
    assert metrics["total_runs"] == 2
    assert metrics["success_count"] == 2
