"""Tests for issue #36: evaluation and experiment endpoints.

Acceptance:
- end-to-end evaluation driven over HTTP (query -> evaluate -> metrics),
- experiment launch + poll for compare_chunking_strategies,
- evaluation failures surface failure_type=evaluation_failure,
- unknown experiment id -> 404 with the standard error envelope.
"""

import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from core.interfaces.retriever import Document

PROMPT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "prompt_config.yaml"

QUERY = "What is artificial intelligence?"
RESPONSE = "Artificial intelligence simulates human intelligence."
DOCS = [
    {"content": "Artificial intelligence simulates human intelligence."},
    {"content": "Machine learning learns patterns from data."},
]


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {
            "response": RESPONSE,
            "retrieved_docs": list(DOCS),
            "retrieval_scores": [0.9, 0.8],
            "metrics": {},
            "failure_tags": [],
            "observability": {"stages": {}},
        }


class _StubEmbedder:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


class _StubRetriever:
    def retrieve(self, embedding, top_k=3):
        return [Document(content=entry["content"]) for entry in DOCS]


class _PipelineWithRetriever(_FakePipeline):
    def __init__(self):
        self.embedder = _StubEmbedder()
        self.retriever = _StubRetriever()
        self.top_k = 3


def _make_app(**kwargs):
    builder = kwargs.pop("pipeline_builder", None)

    def default_builder(**_ignored):
        return (_PipelineWithRetriever() if builder == "retriever" else _FakePipeline())

    return create_app(pipeline_builder=default_builder, **kwargs)


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path) -> tuple:
    models = _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "emb-a",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {
                "emb-a": {"provider": "dummy", "model_name": "emb-a"},
                "emb-b": {"provider": "dummy", "model_name": "emb-b"},
            },
        },
    )
    retrieval = _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "simple",
                "top_k": 2,
                "similarity_metric": "cosine",
                "retrievers": {
                    "simple": {"provider": "simple"},
                    "faiss": {"provider": "faiss"},
                },
            },
            "evaluation": {
                "enabled": True,
                "active_evaluator": "dummy",
                "evaluators": {
                    "dummy": {"provider": "dummy"},
                    "noop": {"provider": "noop"},
                },
            },
            "reranking": {"enabled": False, "active_reranker": "none", "rerankers": {}},
            "chunking": {
                "active_strategy": "small",
                "strategies": {
                    "small": {"chunk_size": 20, "chunk_overlap": 5, "separator": " "},
                    "large": {"chunk_size": 200, "chunk_overlap": 0, "separator": " "},
                },
            },
            "token_budget": {
                "default_mode": "strict",
                "max_output_cap": 512,
                "min_output_tokens": 16,
                "chars_per_token": 4,
            },
            "governance": {"enabled": False},
        },
    )
    return models, retrieval


def _poll_experiment(client, exp_id, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/v1/experiments/{exp_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] != "running":
            return data
        time.sleep(0.1)
    raise AssertionError(f"Experiment {exp_id} did not finish within {timeout}s")


# -- evaluation -----------------------------------------------------------


def test_real_semantic_evaluation_over_http():
    with TestClient(_make_app()) as client:
        response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "retrieved_docs": DOCS},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluator"] == "SemanticEvaluator"
    assert payload["evaluator_key"] == "semantic"
    assert payload["num_retrieved_docs"] == len(DOCS)
    assert payload["docs_source"] == "request"
    metrics = payload["metrics"]
    for key in ("context_precision", "answer_relevance", "faithfulness"):
        assert key in metrics
        assert 0.0 <= float(metrics[key]) <= 1.0
    assert payload["request_id"]


def test_query_then_evaluate_over_http():
    with TestClient(_make_app()) as client:
        query_response = client.post(
            "/v1/query", json={"query": QUERY, "top_k": 2, "include_trace": False}
        )
        assert query_response.status_code == 200
        retrieved = query_response.json()["retrieved_docs"]

        evaluate_response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "retrieved_docs": retrieved},
        )

    assert evaluate_response.status_code == 200
    payload = evaluate_response.json()
    assert payload["metrics"]
    assert payload["num_retrieved_docs"] == len(retrieved)


def test_evaluate_autoretrieves_from_live_pipeline():
    app = _make_app(pipeline_builder="retriever")
    with TestClient(app) as client:
        response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "evaluator": "dummy"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["docs_source"] == "retrieval"
    assert payload["num_retrieved_docs"] == len(DOCS)


def test_evaluate_unknown_evaluator_returns_404_envelope():
    with TestClient(_make_app()) as client:
        response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "retrieved_docs": DOCS,
                  "evaluator": "not-configured"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["failure_type"] == "evaluation_failure"
    assert "unknown_evaluator" in body["failure_tags"]
    assert body["request_id"]


def test_evaluate_evaluator_runtime_error_returns_500_envelope():
    class _BrokenEvaluator:
        def evaluate(self, query, retrieved_docs, response):
            raise RuntimeError("model offline")

    with TestClient(_make_app()) as client:
        service = client.app.state.evaluate
        service.evaluator_registry.create = lambda name=None, enabled=None: _BrokenEvaluator()

        response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "retrieved_docs": DOCS},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["failure_type"] == "evaluation_failure"
    assert body["error"] == "model offline"
    assert body["request_id"]


def test_evaluate_missing_docs_returns_400_envelope():
    app = _make_app()  # fake pipeline exposes no retriever
    with TestClient(app) as client:
        response = client.post(
            "/v1/evaluate", json={"query": QUERY, "response": RESPONSE}
        )

    assert response.status_code == 400
    assert response.json()["failure_type"] == "evaluation_failure"


def test_evaluate_disabled_evaluation_returns_empty_metrics(tmp_path):
    models, retrieval = _tmp_configs(tmp_path)
    payload = yaml.safe_load(retrieval.read_text(encoding="utf-8"))
    payload["evaluation"]["enabled"] = False
    _write_yaml(retrieval, payload)

    with TestClient(
        _make_app(models_config_path=models, retrieval_config_path=retrieval)
    ) as client:
        response = client.post(
            "/v1/evaluate",
            json={"query": QUERY, "response": RESPONSE, "retrieved_docs": DOCS},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"] == {}
    assert body["evaluator"] == "NullEvaluator"


def test_evaluate_ground_truth_echoed_when_unsupported():
    with TestClient(_make_app()) as client:
        response = client.post(
            "/v1/evaluate",
            json={
                "query": QUERY,
                "response": RESPONSE,
                "retrieved_docs": DOCS,
                "evaluator": "dummy",
                "ground_truth": "AI mimics human intelligence.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ground_truth"] == "AI mimics human intelligence."
    assert body["ground_truth_used"] is False


def test_evaluate_503_without_lifespan():
    client = TestClient(_make_app())
    response = client.post(
        "/v1/evaluate", json={"query": QUERY, "response": RESPONSE, "retrieved_docs": DOCS}
    )
    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"


# -- experiments ----------------------------------------------------------


def test_launch_and_poll_compare_chunking_strategies(tmp_path):
    models, retrieval = _tmp_configs(tmp_path)

    with TestClient(
        _make_app(models_config_path=models, retrieval_config_path=retrieval)
    ) as client:
        launch = client.post(
            "/v1/experiments",
            json={
                "kind": "compare_chunking_strategies",
                "query": QUERY,
                "docs": DOCS,
                "embedding_model": "emb-a",
                "retriever_backend": "simple",
                "strategies": ["small", "large"],
                "top_k": 2,
            },
        )
        assert launch.status_code == 202
        launched = launch.json()
        assert launched["status"] == "running"
        assert launched["kind"] == "compare_chunking_strategies"

        finished = _poll_experiment(client, launched["id"])

    assert finished["status"] == "completed"
    assert finished["failure_type"] is None
    result = finished["result"]
    assert result["strategies_compared"] == ["small", "large"]
    assert set(result["results"]) == {"small", "large"}
    assert result["results"]["small"]["num_indexed_chunks"] >= 1
    assert finished["finished_at"] >= finished["created_at"]


def test_launch_single_experiment_completes(tmp_path):
    models, retrieval = _tmp_configs(tmp_path)

    with TestClient(
        _make_app(models_config_path=models, retrieval_config_path=retrieval)
    ) as client:
        launch = client.post(
            "/v1/experiments",
            json={
                "kind": "single",
                "query": QUERY,
                "docs": DOCS,
                "embedding_model": "emb-a",
                "retriever_backend": "simple",
                "top_k": 2,
            },
        )
        assert launch.status_code == 202
        finished = _poll_experiment(client, launch.json()["id"])

    assert finished["status"] == "completed"
    assert finished["result"]["query"] == QUERY
    assert finished["result"]["retriever"] == "SimpleRetriever"


def test_unknown_experiment_id_returns_404_envelope():
    with TestClient(_make_app()) as client:
        response = client.get("/v1/experiments/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["failure_type"] == "unknown_failure"
    assert "experiment_not_found" in body["failure_tags"]
    assert body["request_id"]


def test_failed_experiment_reports_failure_type(tmp_path):
    models, retrieval = _tmp_configs(tmp_path)

    with TestClient(
        _make_app(models_config_path=models, retrieval_config_path=retrieval)
    ) as client:
        runner = client.app.state.evaluate.experiment_runner

        def _explode(*args, **kwargs):
            raise RuntimeError("index build failed")

        runner.compare_chunking_strategies = _explode
        launch = client.post(
            "/v1/experiments",
            json={
                "kind": "compare_chunking_strategies",
                "query": QUERY,
                "docs": DOCS,
                "strategies": ["small", "large"],
            },
        )
        assert launch.status_code == 202
        finished = _poll_experiment(client, launch.json()["id"])

    assert finished["status"] == "failed"
    assert finished["error"] == "index build failed"
    assert finished["failure_type"] == "unknown_failure"
    assert finished["result"] is None


def test_experiment_with_missing_documents_path_returns_400():
    with TestClient(_make_app()) as client:
        response = client.post(
            "/v1/experiments",
            json={"kind": "single", "query": QUERY, "documents_path": "data/nope.json"},
        )

    assert response.status_code == 400
    assert response.json()["failure_type"] == "unknown_failure"


def test_experiment_503_without_lifespan():
    client = TestClient(_make_app())
    response = client.post("/v1/experiments", json={"kind": "single", "query": QUERY})
    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"


def test_openapi_exposes_evaluation_schemas():
    client = TestClient(_make_app())
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    for name in (
        "EvaluateRequest",
        "EvaluateResponse",
        "ExperimentLaunchRequest",
        "ExperimentLaunchResponse",
        "ExperimentStatusResponse",
    ):
        assert name in components
    assert "/v1/evaluate" in schema["paths"]
    assert "/v1/experiments" in schema["paths"]
    assert "/v1/experiments/{exp_id}" in schema["paths"]
