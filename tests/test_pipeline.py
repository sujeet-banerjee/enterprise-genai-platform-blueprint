from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator

from app.pipeline import RAGPipeline
from core.services.cost_tracker import CostTracker


def test_pipeline_run():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        evaluator=DummyEvaluator(),
        cost_tracker=CostTracker()
    )

    result = pipeline.run("What is AI?")

    assert "response" in result
    assert "retrieved_docs" in result
    assert "metrics" in result
    assert "cost" in result

    assert isinstance(result["retrieved_docs"], list)
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["cost"], dict)