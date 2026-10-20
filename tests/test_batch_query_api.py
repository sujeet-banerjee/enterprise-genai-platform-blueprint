"""Tests for issue #39: batch query endpoint POST /v1/query:batch.

Acceptance:
- one standard result envelope per query (each with request_id + cost/latency)
  plus an aggregate summary,
- a failing query does not abort the batch (partial success),
- governance applies per query and totals are reported,
- oversized batches are rejected with a 4xx standard envelope.
"""

from collections import deque
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

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


def _tmp_configs(tmp_path: Path, *, max_batch_size: int = 25):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", OBSERVABILITY_YAML
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml",
            """
enabled: true
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
history_max_runs: 1000
trace_store_max: 500
max_batch_size: {max_batch_size}
""",
        ),
    }


def _success(cost=0.002, total_ms=35.0):
    return {
        "response": "answer",
        "failure_tags": [],
        "cost": {
            "estimated_cost_usd": cost,
            "model": "dummy",
            "input_tokens": 3,
            "output_tokens": 2,
        },
        "latency": {"embedding": 10.0, "llm_generation": 25.0, "total_ms": total_ms},
        "observability": {"status": "success", "api_key": "sk-live-secret"},
    }


def _failure(failure_type="llm_failure", total_ms=3.0):
    return {
        "response": None,
        "error": "boom",
        "failure_type": failure_type,
        "failure_tags": [failure_type],
        "cost": {},
        "latency": {"embedding": 3.0, "total_ms": total_ms},
        "observability": {"status": "failed", "failure_tags": [failure_type]},
    }


def _app(config_paths, results):
    scripted = _ScriptedPipeline(results)

    def builder(**_ignored):
        return scripted

    return create_app(pipeline_builder=builder, **config_paths)


def _post_batch(client, queries, *, request_id="batch-1", **extra):
    payload = {"queries": queries}
    payload.update(extra)
    return client.post("/v1/query:batch", json=payload, headers={"X-Request-ID": request_id})


# -- happy path / summary -------------------------------------------------


def test_batch_happy_path_returns_envelope_per_query(tmp_path):
    results = [_success(), _success(), _success()]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        response = _post_batch(client, ["q1", "q2", "q3"])

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "batch-1"
    assert len(body["results"]) == 3
    for index, item in enumerate(body["results"]):
        assert item["response"] == "answer"
        assert item["request_id"] == f"batch-1-{index}"
        assert item["cost"]["estimated_cost_usd"] == 0.002
        assert item["latency"]["total_ms"] == 35.0
    assert body["summary"] == {
        "batch_size": 3,
        "succeeded": 3,
        "failed": 0,
        "by_failure_type": {},
        "total_cost_usd": 0.006,
        "total_latency_ms": 105.0,
    }


def test_batch_partial_failure_does_not_abort(tmp_path):
    results = [_success(cost=0.001), _failure(), _success(cost=0.004)]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        response = _post_batch(client, ["ok", "bad", "ok"])

    assert response.status_code == 200
    body = response.json()
    assert [bool(item.get("error")) for item in body["results"]] == [False, True, False]
    summary = body["summary"]
    assert summary["succeeded"] == 2
    assert summary["failed"] == 1
    assert summary["by_failure_type"] == {"llm_failure": 1}
    assert summary["total_cost_usd"] == 0.005
    assert body["results"][1]["failure_type"] == "llm_failure"


def test_batch_all_failures_still_returns_200(tmp_path):
    results = [_failure(), _failure(failure_type="retrieval_failure")]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        response = _post_batch(client, ["q1", "q2"])

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["succeeded"] == 0
    assert summary["failed"] == 2
    assert summary["by_failure_type"] == {"llm_failure": 1, "retrieval_failure": 1}


def test_batch_cost_limit_exceeded_reported_in_summary(tmp_path):
    results = [_success(), _failure(failure_type="cost_limit_exceeded")]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        response = _post_batch(client, ["q1", "q2"])

    body = response.json()
    assert body["summary"]["by_failure_type"] == {"cost_limit_exceeded": 1}
    assert body["results"][1]["failure_type"] == "cost_limit_exceeded"


# -- cap / validation -----------------------------------------------------


def test_batch_beyond_cap_returns_400_envelope(tmp_path):
    config_paths = _tmp_configs(tmp_path, max_batch_size=2)
    with TestClient(_app(config_paths, [_success()])) as client:
        response = _post_batch(client, ["q1", "q2", "q3"])

    assert response.status_code == 400
    body = response.json()
    assert body["failure_type"] == "batch_too_large"
    assert body["failure_tags"] == ["batch_too_large"]
    assert body["request_id"] == "batch-1"


def test_batch_at_cap_is_accepted(tmp_path):
    config_paths = _tmp_configs(tmp_path, max_batch_size=2)
    with TestClient(_app(config_paths, [_success(), _success()])) as client:
        response = _post_batch(client, ["q1", "q2"])

    assert response.status_code == 200
    assert response.json()["summary"]["batch_size"] == 2


def test_batch_empty_queries_rejected(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path), [_success()])) as client:
        response = _post_batch(client, [])

    assert response.status_code == 422


# -- governance / traces / history ---------------------------------------


def test_batch_governance_accounting_per_query(tmp_path):
    results = [_success(cost=0.002), _success(cost=0.003), _success(cost=0.001)]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        _post_batch(client, ["q1", "q2", "q3"])
        status = client.get("/v1/governance/status").json()
        metrics = client.get("/v1/metrics").json()

    assert status["window"]["requests"] == 3
    assert status["window"]["total_cost_usd"] == 0.006
    assert metrics["total_runs"] == 3
    assert metrics["success_count"] == 3


def test_batch_include_trace_toggle(tmp_path):
    results = [_success(), _success(), _success(), _success()]
    with TestClient(_app(_tmp_configs(tmp_path), results)) as client:
        with_trace = _post_batch(client, ["q1", "q2"], include_trace=True).json()
        without_trace = _post_batch(
            client, ["q3", "q4"], request_id="batch-2", include_trace=False
        ).json()

    assert all("observability" in item for item in with_trace["results"])
    assert all("observability" not in item for item in without_trace["results"])


def test_batch_503_without_lifespan(tmp_path):
    client = TestClient(_app(_tmp_configs(tmp_path), []))
    response = _post_batch(client, ["q1"])

    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"
