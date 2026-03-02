from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator

from core.services.cost_tracker import CostTracker
from core.services.token_budget_service import TokenBudgetService
from core.services.prompt_builder import PromptBuilder
from core.config.generation_config import GenerationConfig

from app.pipeline import RAGPipeline


def build_test_pipeline():
    return RAGPipeline(
        embedder=DummyEmbedder(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        evaluator=DummyEvaluator(),
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=CostTracker()
    )


def test_pipeline_run():
    pipeline = build_test_pipeline()

    result = pipeline.run("What is AI?")

    assert "response" in result
    assert "retrieved_docs" in result
    assert "metrics" in result
    assert "cost" in result
    assert "token_budget" in result

    assert isinstance(result["retrieved_docs"], list)
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["cost"], dict)
    assert isinstance(result["token_budget"], dict)