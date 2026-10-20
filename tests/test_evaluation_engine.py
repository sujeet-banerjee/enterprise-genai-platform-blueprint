"""Tests for issue #21: EvaluationEngine must compute genuine metrics.

The engine no longer fabricates ``similarity_score=0.8`` / ``supported_claims=9``
/ ``total_claims=10`` placeholders. Metrics are derived from real embedding
inference (shared with ``SemanticEvaluator``), so different inputs yield
different scores. These tests use the real MiniLM embedder via conftest fixtures.
"""

from core.evaluation.evaluation_engine import EvaluationEngine
from core.evaluation.metrics import Metrics
from core.interfaces.retriever import Document

AI_DOC = Document(content="Artificial intelligence is the simulation of human intelligence.")
WEATHER_DOC = Document(content="Rain is liquid water falling from clouds.")


def test_evaluation_engine_returns_real_metrics(real_embedder):
    engine = EvaluationEngine(embedder=real_embedder)
    result = engine.evaluate(
        query="What is artificial intelligence?",
        docs=[AI_DOC],
        response="Artificial intelligence simulates human intelligence.",
    )
    assert set(result) == {"context_precision", "answer_relevance", "faithfulness"}
    assert all(0.0 <= value <= 1.0 for value in result.values())
    assert result["context_precision"] > 0.0


def test_engine_metrics_vary_with_input(real_embedder):
    """Regression for #21: the old engine returned constants for any input."""
    engine = EvaluationEngine(embedder=real_embedder)
    relevant = engine.evaluate(
        query="What is artificial intelligence?",
        docs=[AI_DOC],
        response="Artificial intelligence simulates human intelligence.",
    )
    irrelevant = engine.evaluate(
        query="What is artificial intelligence?",
        docs=[WEATHER_DOC],
        response="Bananas are a yellow fruit.",
    )
    assert relevant != irrelevant
    assert relevant["context_precision"] > irrelevant["context_precision"]
    assert relevant["answer_relevance"] > irrelevant["answer_relevance"]


def test_engine_empty_docs_zero_context_metrics(real_embedder):
    engine = EvaluationEngine(embedder=real_embedder)
    result = engine.evaluate(query="What is AI?", docs=[], response="AI is intelligence.")
    assert result["context_precision"] == 0.0
    assert result["faithfulness"] == 0.0


def test_engine_does_not_use_placeholder_constants(real_embedder):
    """The fabricated 0.8 similarity / 9-of-10 claims must be gone."""
    engine = EvaluationEngine(embedder=real_embedder)
    result = engine.evaluate(
        query="What is quantum computing?",
        docs=[WEATHER_DOC],
        response="Quantum computing uses qubits.",
    )
    assert result["answer_relevance"] != 0.8
    assert result["faithfulness"] != 0.9


def test_engine_supports_ground_truth(real_embedder):
    engine = EvaluationEngine(embedder=real_embedder)
    assert engine.supports_ground_truth is True
    metrics = engine.evaluate_with_ground_truth(
        query="What is artificial intelligence?",
        docs=[AI_DOC],
        response="Artificial intelligence simulates human intelligence.",
        ground_truth="Artificial intelligence is the simulation of human intelligence in machines.",
    )
    assert "answer_correctness" in metrics
    assert 0.0 <= metrics["answer_correctness"] <= 1.0


def test_registry_builds_genuine_engine_evaluator():
    from core.registry.evaluator_registry import EvaluatorRegistry

    registry = EvaluatorRegistry()
    assert isinstance(registry.create("engine"), EvaluationEngine)


def test_engine_is_consistent_with_semantic_evaluator(real_embedder):
    from core.implementations.semantic_evaluator import SemanticEvaluator

    engine = EvaluationEngine(embedder=real_embedder)
    semantic = SemanticEvaluator(embedder=real_embedder)
    args = dict(query="What is AI?", docs=[AI_DOC], response="AI is intelligence.")
    assert engine.evaluate(**args) == semantic.evaluate(
        query=args["query"], retrieved_docs=args["docs"], response=args["response"]
    )


# -- Metrics lexical helper -------------------------------------------------


def test_context_precision_query_mode():
    score = Metrics.context_precision(
        retrieved_docs=["AI is intelligence", "ML is learning"],
        query="What is AI",
    )
    assert 0.0 <= score <= 1.0


def test_context_precision_ground_truth_mode_exact_match():
    docs = [Document(content="a"), Document(content="b")]
    score = Metrics.context_precision(
        relevant_docs=["a"],
        retrieved_docs=docs,
    )
    assert score == 0.5


def test_context_precision_empty_retrieved_is_zero():
    assert Metrics.context_precision(query="q", retrieved_docs=[]) == 0.0
