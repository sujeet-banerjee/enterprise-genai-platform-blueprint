from core.evaluation.evaluation_engine import EvaluationEngine
from core.evaluation.metrics import Metrics
from core.interfaces.retriever import Document


def test_evaluation_engine_returns_real_metrics():
    engine = EvaluationEngine(Metrics())
    docs = [Document(content="Artificial intelligence is the simulation of human intelligence.")]

    result = engine.evaluate(
        query="What is artificial intelligence?",
        docs=docs,
        response="Artificial intelligence simulates human intelligence.",
    )

    assert set(result) == {"context_precision", "answer_relevance", "faithfulness"}
    assert all(0.0 <= value <= 1.0 for value in result.values())
    assert result["context_precision"] > 0.0
