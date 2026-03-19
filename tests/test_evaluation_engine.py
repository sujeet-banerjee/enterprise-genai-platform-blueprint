from core.evaluation.evaluation_engine import EvaluationEngine

class MockMetrics:

    def context_precision(self, *args, **kwargs):
        return 0.75

    def answer_relevance(self, *args, **kwargs):
        return 0.8

    def faithfulness(self, *args, **kwargs):
        return 0.9

def test_evaluation_engine_returns_metrics():

    metrics = MockMetrics()
    engine = EvaluationEngine(metrics)

    result = engine.evaluate(
        query="What is AI?",
        docs=["doc1", "doc2"],
        response="AI is artificial intelligence."
    )

    assert "context_precision" in result
    assert "answer_relevance" in result
    assert "faithfulness" in result

    assert result["context_precision"] == metrics.context_precision()