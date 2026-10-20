"""Tests for issue #27: batching / parallel inference.

Covers the ``embed_batch`` / ``generate_batch`` provider hooks (batch == loop of
single-item calls), ``RAGPipeline.run_batch`` (sequential + parallel, order
preserved), and the parallel batch API endpoint.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_llm import DummyLLM

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"


# -- provider-level batch hooks -------------------------------------------


def test_default_embed_batch_matches_loop():
    embedder = DummyEmbedder(dimension=7)
    texts = ["alpha", "beta", "gamma"]
    assert embedder.embed_batch(texts) == [embedder.embed(t) for t in texts]


def test_default_generate_batch_matches_loop():
    llm = DummyLLM()
    prompts = ["p1", "p2", "p3"]
    assert llm.generate_batch(prompts) == [llm.generate(p) for p in prompts]


def test_simple_embedder_embed_batch_matches_single(real_embedder):
    texts = [
        "Artificial Intelligence is the simulation of human intelligence.",
        "Neural networks are inspired by the human brain.",
        "Machine Learning is a subset of AI.",
    ]
    batched = real_embedder.embed_batch(texts)
    singles = [real_embedder.embed(t) for t in texts]
    assert len(batched) == len(texts)
    for b, s in zip(batched, singles):
        assert len(b) == real_embedder.dimension
        # Real batching must be numerically equivalent (float-exact).
        assert b == pytest.approx(s, abs=1e-5)


def test_simple_embedder_embed_batch_empty(real_embedder):
    assert real_embedder.embed_batch([]) == []


def test_local_llm_generate_batch_real(real_llm):
    prompts = ["What is AI?", "What is machine learning?"]
    outputs = real_llm.generate_batch(prompts)
    assert len(outputs) == 2
    assert all(isinstance(o, str) for o in outputs)


def test_local_llm_generate_batch_empty(real_llm):
    assert real_llm.generate_batch([]) == []


# -- pipeline run_batch ----------------------------------------------------


def test_pipeline_run_batch_sequential_matches_single(make_pipeline):
    pipeline = make_pipeline(reranker=None)
    queries = ["What is deep learning?", "What is a neural network?"]
    batch = pipeline.run_batch(queries, raise_on_failure=False)
    singles = [pipeline.run(q, raise_on_failure=False) for q in queries]
    assert [r["response"] for r in batch] == [r["response"] for r in singles]


def test_pipeline_run_batch_parallel_preserves_order(make_pipeline):
    pipeline = make_pipeline(reranker=None)
    queries = ["What is AI?", "What is ML?", "What is a neural network?"]
    parallel = pipeline.run_batch(queries, max_workers=3, raise_on_failure=False)
    assert [r["response"] for r in parallel] == [
        pipeline.run(q, raise_on_failure=False)["response"] for q in queries
    ]


def test_pipeline_run_batch_empty(make_pipeline):
    pipeline = make_pipeline(reranker=None)
    assert pipeline.run_batch([]) == []


# -- parallel batch API ----------------------------------------------------

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


class _CountingPipeline:
    """Echo pipeline recording concurrent invocation via a unique token."""

    def __init__(self):
        self.calls = []

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        self.calls.append(query)
        return {
            "response": f"answer:{query}",
            "failure_tags": [],
            "cost": {"estimated_cost_usd": 0.0},
            "latency": {"total_ms": 1.0},
            "observability": {"status": "success"},
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path, *, batch_max_workers: int = 4):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml",
            "enabled: true\nmax_cost_per_request_usd: 0.5\nsafety_margin_tokens: 128\n"
            "avg_chunk_tokens: 300\n",
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\n"
            "history_max_runs: 1000\ntrace_store_max: 500\nmax_batch_size: 25\n"
            f"batch_max_workers: {batch_max_workers}\n",
        ),
    }


def _app(config_paths, pipeline):
    def builder(**_ignored):
        return pipeline

    return create_app(pipeline_builder=builder, **config_paths)


def test_batch_api_parallel_preserves_order(tmp_path):
    pipeline = _CountingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path), pipeline)) as client:
        response = client.post(
            "/v1/query:batch",
            json={"queries": ["q1", "q2", "q3"], "parallel": True, "max_workers": 3},
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["response"] for item in body["results"]] == [
        "answer:q1",
        "answer:q2",
        "answer:q3",
    ]
    assert body["summary"]["succeeded"] == 3
    assert sorted(pipeline.calls) == ["q1", "q2", "q3"]


def test_batch_api_parallel_default_sequential(tmp_path):
    pipeline = _CountingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path), pipeline)) as client:
        response = client.post("/v1/query:batch", json={"queries": ["a", "b"]})

    assert response.status_code == 200
    assert [item["response"] for item in response.json()["results"]] == [
        "answer:a",
        "answer:b",
    ]


def test_batch_api_clamps_max_workers(tmp_path):
    pipeline = _CountingPipeline()
    # batch_max_workers=2 caps an explicit max_workers=99 without erroring.
    with TestClient(_app(_tmp_configs(tmp_path, batch_max_workers=2), pipeline)) as client:
        response = client.post(
            "/v1/query:batch",
            json={"queries": ["q1", "q2", "q3"], "parallel": True, "max_workers": 99},
        )

    assert response.status_code == 200
    assert response.json()["summary"]["succeeded"] == 3
