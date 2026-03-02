from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_retriever import DummyRetriever
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


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

def test_token_budget_reduces_output():
    pipeline = build_test_pipeline()

    # Force small max tokens
    pipeline.generation_config.max_tokens = 100

    result = pipeline.run("Short question?")

    assert result["token_budget"]["allowed_output_tokens"] <= 100