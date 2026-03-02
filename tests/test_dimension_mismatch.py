from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_retriever import DummyRetriever
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


class BadRetriever(DummyRetriever):
    @property
    def index_dimension(self):
        return 999  # mismatch


def test_dimension_mismatch_raises():
    from pytest import raises

    with raises(ValueError):
        RAGPipeline(
            embedder=DummyEmbedder(),
            prompt_builder=PromptBuilder("config/prompt_config.yaml"),
            retriever=BadRetriever(),
            llm=DummyLLM(),
            token_budget_service=TokenBudgetService(policy_mode="strict"),
            evaluator=DummyEvaluator(),
            generation_config=GenerationConfig(max_tokens=512),
            cost_tracker=CostTracker()
        )