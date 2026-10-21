"""Tests for issue #41: OpenAPI snapshot + error-envelope contract.

Locks the public API surface and the error envelope so P2/P3 work cannot drift
silently. Covers:
- the route set matches a checked-in allowlist,
- every 4xx/5xx envelope carries {error, failure_type, failure_tags, request_id}
  and its ``failure_type`` is a member of the ``FailureType`` taxonomy,
- the legacy ``POST /query`` alias matches ``POST /v1/query``,
- ``X-Request-ID`` is echoed on every response,
- config/trace responses never leak redacted secrets.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.failure_classifier import FailureType

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"

# Deliberate allowlist of public routes (issue #41 snapshot). Adding an endpoint
# requires updating this set on purpose.
EXPECTED_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/query",
    "/v1/query",
    "/v1/query:batch",
    "/v1/config",
    "/v1/models",
    "/v1/embedding-models",
    "/v1/retrievers",
    "/v1/rerankers",
    "/v1/evaluators",
    "/v1/evaluate",
    "/v1/experiments",
    "/v1/experiments/{exp_id}",
    "/v1/pipeline:rebuild",
    "/v1/governance/status",
    "/v1/traces/{request_id}",
    "/v1/metrics",
    "/v1/audit",
    "/v1/access",
}

ENVELOPE_KEYS = {"error", "failure_type", "failure_tags", "request_id"}

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


class _FakePipeline:
    def __init__(self, *, fail: bool = False, secret: str = "sk-live-secret"):
        self.fail = fail
        self.secret = secret

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        if self.fail:
            return {
                "response": None,
                "error": "boom",
                "failure_type": FailureType.LLM_FAILURE.value,
                "failure_tags": [FailureType.LLM_FAILURE.value],
                "observability": {"request_id": request_id},
            }
        return {
            "response": f"echo:{query}",
            "failure_tags": [],
            "cost": {"estimated_cost_usd": 0.001},
            "latency": {"total_ms": 5.0},
            "observability": {
                "request_id": request_id,
                "api_key": self.secret,
            },
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path, *, api_key: str = "", require_api_key: bool = False):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml",
            "log_level: INFO\nredact_sensitive_data: true\n",
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml",
            "enabled: true\nmax_cost_per_request_usd: 0.5\n",
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            f"""
require_api_key: {"true" if require_api_key else "false"}
api_key: "{api_key}"
allow_rebuild: false
history_max_runs: 100
trace_store_max: 50
max_batch_size: 2
""",
        ),
    }


def _app(config_paths, pipeline=None):
    pipeline = pipeline or _FakePipeline()

    def builder(**_ignored):
        return pipeline

    return create_app(pipeline_builder=builder, **config_paths)


# -- OpenAPI snapshot -----------------------------------------------------


def test_openapi_paths_match_allowlist(tmp_path):
    app = _app(_tmp_configs(tmp_path))
    with TestClient(app):
        paths = set(app.openapi()["paths"].keys())

    assert paths == EXPECTED_PATHS, f"route drift: {paths ^ EXPECTED_PATHS}"


def test_openapi_removed_endpoint_fails_snapshot(tmp_path):
    # Guard semantics: the snapshot is a real set comparison, so any route that
    # disappears (or is renamed) is caught.
    app = _app(_tmp_configs(tmp_path))
    with TestClient(app):
        paths = set(app.openapi()["paths"].keys())

    missing = EXPECTED_PATHS - paths
    assert not missing, f"endpoints removed without updating the snapshot: {missing}"


# -- error envelope contract ----------------------------------------------


def _assert_envelope(body):
    assert ENVELOPE_KEYS.issubset(body.keys()), body
    assert body["failure_type"] in {ft.value for ft in FailureType}
    assert isinstance(body["failure_tags"], list)
    assert body["request_id"]


def test_envelope_contract_on_503_not_ready(tmp_path):
    client = TestClient(_app(_tmp_configs(tmp_path), _FakePipeline()))
    response = client.get("/v1/metrics")

    assert response.status_code == 503
    body = response.json()
    _assert_envelope(body)
    assert body["failure_type"] == FailureType.NOT_READY.value


def test_envelope_contract_on_401_unauthorized(tmp_path):
    config_paths = _tmp_configs(tmp_path, api_key="s3cr3t", require_api_key=True)
    with TestClient(_app(config_paths)) as client:
        response = client.get("/v1/models")

    assert response.status_code == 401
    body = response.json()
    _assert_envelope(body)
    assert body["failure_type"] == FailureType.UNAUTHORIZED.value


def test_envelope_contract_on_400_batch_too_large(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path))) as client:
        response = client.post("/v1/query:batch", json={"queries": ["a", "b", "c"]})

    assert response.status_code == 400
    body = response.json()
    _assert_envelope(body)
    assert body["failure_type"] == FailureType.BATCH_TOO_LARGE.value


def test_envelope_contract_on_404_trace_miss(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path))) as client:
        response = client.get("/v1/traces/missing")

    assert response.status_code == 404
    body = response.json()
    _assert_envelope(body)
    assert body["failure_type"] == FailureType.UNKNOWN_FAILURE.value


@pytest.mark.parametrize("failure_type", [ft.value for ft in FailureType])
def test_failure_type_members_are_envelope_compatible(failure_type):
    # Data-driven: every taxonomy member is a plain lowercase snake_case string,
    # so it can appear in an envelope unchanged.
    assert failure_type == failure_type.lower()
    assert failure_type.replace("_", "").isalpha()


def test_taxonomy_contains_expected_13_pipeline_types():
    pipeline_types = {
        FailureType.EMBEDDING_FAILURE.value,
        FailureType.DIMENSION_MISMATCH.value,
        FailureType.RETRIEVAL_FAILURE.value,
        FailureType.NO_DOCUMENTS_RETRIEVED.value,
        FailureType.LOW_RETRIEVAL_SCORE.value,
        FailureType.RERANKING_FAILURE.value,
        FailureType.TOKEN_BUDGET_EXCEEDED.value,
        FailureType.COST_LIMIT_EXCEEDED.value,
        FailureType.RETRIEVAL_POLICY_FAILURE.value,
        FailureType.PROMPT_CONSTRUCTION_FAILURE.value,
        FailureType.LLM_FAILURE.value,
        FailureType.EVALUATION_FAILURE.value,
        FailureType.UNKNOWN_FAILURE.value,
    }
    assert len(pipeline_types) == 13
    assert pipeline_types.issubset({ft.value for ft in FailureType})


# -- legacy parity / header / redaction -----------------------------------


def test_legacy_query_matches_v1_query(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path))) as client:
        v1 = client.post("/v1/query", json={"query": "hello", "include_trace": False})
        legacy = client.post("/query", json={"query": "hello", "include_trace": False})

    assert v1.status_code == legacy.status_code == 200
    assert v1.json()["response"] == legacy.json()["response"]
    assert set(v1.json().keys()) == set(legacy.json().keys())


def test_request_id_header_echoed_on_every_response(tmp_path):
    with TestClient(_app(_tmp_configs(tmp_path))) as client:
        responses = [
            client.get("/health"),
            client.get("/ready"),
            client.get("/v1/config"),
            client.get("/v1/metrics"),
            client.post("/v1/query", json={"query": "hi"}),
            client.post("/v1/query:batch", json={"queries": ["a"]}),
            client.get("/v1/traces/missing"),
        ]

    for response in responses:
        assert response.headers.get("X-Request-ID")


def test_config_and_trace_never_leak_secrets(tmp_path):
    secret = "sk-live-super-secret"
    pipeline = _FakePipeline(secret=secret)
    with TestClient(_app(_tmp_configs(tmp_path), pipeline)) as client:
        client.post("/v1/query", json={"query": "hi"}, headers={"X-Request-ID": "rid-1"})
        config_text = client.get("/v1/config").text
        trace_text = client.get("/v1/traces/rid-1").text

    assert secret not in config_text
    assert secret not in trace_text
    import json

    assert json.loads(trace_text)["api_key"] == "[REDACTED]"
