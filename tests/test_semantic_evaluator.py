import pytest

from core.implementations.semantic_evaluator import SemanticEvaluator
from core.interfaces.retriever import Document


@pytest.fixture(scope="module")
def evaluator():
    return SemanticEvaluator()


def test_metrics_are_in_unit_range(evaluator):
    docs = [Document(content="Artificial intelligence is the simulation of human intelligence.")]
    metrics = evaluator.evaluate(
        "What is artificial intelligence?",
        docs,
        "Artificial intelligence simulates human intelligence.",
    )
    assert set(metrics) == {"context_precision", "answer_relevance", "faithfulness"}
    assert all(0.0 <= value <= 1.0 for value in metrics.values())


def test_relevant_answer_scores_higher_than_irrelevant(evaluator):
    docs = [Document(content="Artificial intelligence is the simulation of human intelligence.")]
    relevant = evaluator.evaluate(
        "What is artificial intelligence?",
        docs,
        "Artificial intelligence simulates human intelligence in machines.",
    )["answer_relevance"]
    irrelevant = evaluator.evaluate(
        "What is artificial intelligence?",
        docs,
        "Bananas are a yellow fruit rich in potassium.",
    )["answer_relevance"]
    assert relevant > irrelevant


def test_no_documents_yields_zero_context_metrics(evaluator):
    metrics = evaluator.evaluate("What is AI?", [], "AI is intelligence.")
    assert metrics["context_precision"] == 0.0
    assert metrics["faithfulness"] == 0.0


def test_registry_builds_semantic_evaluator():
    from core.registry.evaluator_registry import EvaluatorRegistry

    registry = EvaluatorRegistry()
    built = registry.create(name="semantic")
    assert isinstance(built, SemanticEvaluator)
