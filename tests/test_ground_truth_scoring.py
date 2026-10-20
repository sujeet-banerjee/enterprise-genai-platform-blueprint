"""Ground-truth scoring tests for issue #42.

Covers the evaluator-level ground-truth contract:

* ``SemanticEvaluator`` genuinely consumes a reference answer (embedding-based).
* Evaluators without support keep reporting ``ground_truth_used=false``.
* ``POST /v1/evaluate`` reports ``ground_truth_used`` honestly for both cases.

All embedding work uses the real MiniLM model (see ``tests/conftest.py``); no
API keys are required.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.semantic_evaluator import SemanticEvaluator
from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.retriever import Document

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"

QUERY = "What is artificial intelligence?"
ANSWER = "Artificial intelligence simulates human intelligence in machines."
GT_MATCH = "Artificial intelligence is the simulation of human intelligence in machines."
GT_OTHER = "Bananas are a yellow fruit rich in potassium."

DOCS = ["Artificial intelligence is the simulation of human intelligence in machines."]


@pytest.fixture(scope="module")
def evaluator():
    return SemanticEvaluator()


# -- contract / capability -------------------------------------------------


def test_semantic_evaluator_declares_ground_truth_support(evaluator):
    assert evaluator.supports_ground_truth is True


def test_base_evaluator_defaults_to_no_ground_truth_support():
    assert BaseEvaluator.supports_ground_truth is False
    assert DummyEvaluator().supports_ground_truth is False


def test_base_default_falls_back_to_plain_evaluate():
    dummy = DummyEvaluator()
    docs = [Document(content="c")]
    assert dummy.evaluate_with_ground_truth(
        query="q", retrieved_docs=docs, response="r", ground_truth="g"
    ) == dummy.evaluate("q", docs, "r")


# -- semantic metrics ------------------------------------------------------


def test_ground_truth_adds_similarity_and_correctness(evaluator):
    metrics = evaluator.evaluate_with_ground_truth(
        query=QUERY,
        retrieved_docs=[Document(content=DOCS[0])],
        response=ANSWER,
        ground_truth=GT_MATCH,
    )
    assert set(metrics) >= {
        "context_precision",
        "answer_relevance",
        "faithfulness",
        "ground_truth_similarity",
        "answer_correctness",
    }
    assert all(0.0 <= value <= 1.0 for value in metrics.values())


def test_matching_answer_scores_higher_than_unrelated(evaluator):
    docs = [Document(content=DOCS[0])]
    matching = evaluator.evaluate_with_ground_truth(
        query=QUERY, retrieved_docs=docs, response=ANSWER, ground_truth=GT_MATCH
    )["answer_correctness"]
    unrelated = evaluator.evaluate_with_ground_truth(
        query=QUERY, retrieved_docs=docs, response=ANSWER, ground_truth=GT_OTHER
    )["answer_correctness"]
    assert matching > unrelated


def test_multiple_references_use_best_match(evaluator):
    docs = [Document(content=DOCS[0])]
    metrics = evaluator.evaluate_with_ground_truth(
        query=QUERY,
        retrieved_docs=docs,
        response=ANSWER,
        ground_truth=[GT_OTHER, GT_MATCH],
    )
    assert metrics["ground_truth_similarity"] == metrics["answer_correctness"]
    assert metrics["answer_correctness"] > 0.0


def test_missing_or_empty_ground_truth_returns_base_metrics(evaluator):
    docs = [Document(content=DOCS[0])]
    base = evaluator.evaluate(query=QUERY, retrieved_docs=docs, response=ANSWER)
    for reference in (None, "", []):
        metrics = evaluator.evaluate_with_ground_truth(
            query=QUERY, retrieved_docs=docs, response=ANSWER, ground_truth=reference
        )
        assert metrics == base
        assert "answer_correctness" not in metrics


# -- API wiring ------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _make_app(tmp_path: Path) -> "object":
    models = _write(
        tmp_path / "models.yaml",
        """
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
""",
    )
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: true
  active_evaluator: semantic
  evaluators:
    dummy:
      provider: dummy
    semantic:
      provider: semantic
reranking:
  enabled: false
""",
    )
    return create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=REPO_PROMPT,
    )


def test_api_reports_ground_truth_used_for_semantic(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        response = client.post(
            "/v1/evaluate",
            json={
                "query": QUERY,
                "response": ANSWER,
                "retrieved_docs": DOCS,
                "ground_truth": GT_MATCH,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["evaluator"] == "SemanticEvaluator"
    assert body["ground_truth_used"] is True
    assert "answer_correctness" in body["metrics"]


def test_api_reports_ground_truth_unused_for_dummy(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        response = client.post(
            "/v1/evaluate",
            json={
                "query": QUERY,
                "response": ANSWER,
                "retrieved_docs": DOCS,
                "evaluator": "dummy",
                "ground_truth": GT_MATCH,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ground_truth_used"] is False
    assert body["ground_truth"] == GT_MATCH
    assert "answer_correctness" not in body["metrics"]
