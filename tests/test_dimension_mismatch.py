import pytest

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


class _MismatchedRetriever(BaseRetriever):
    """Retriever whose index dimension deliberately disagrees with the embedder."""

    @property
    def index_dimension(self) -> int:
        return 999

    def retrieve_with_scores(self, embedding, top_k: int = 3):
        return [ScoredDocument(document=Document(content="doc"), score=0.9)]

    def retrieve(self, embedding, top_k: int = 3):
        return [Document(content="doc")]


def test_dimension_mismatch_raises(real_embedder, real_llm, semantic_evaluator):
    with pytest.raises(ValueError):
        RAGPipeline(
            embedder=real_embedder,
            prompt_builder=PromptBuilder("config/prompt_config.yaml"),
            retriever=_MismatchedRetriever(),
            llm=real_llm,
            token_budget_service=TokenBudgetService(policy_mode="strict"),
            evaluator=semantic_evaluator,
            generation_config=GenerationConfig(max_tokens=64),
            cost_tracker=CostTracker(),
        )
