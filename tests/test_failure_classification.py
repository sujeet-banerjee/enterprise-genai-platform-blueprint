import pytest
from core.observability.failure_classifier import FailureType, FailureClassifier
from app.pipeline import RAGPipeline
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService
from core.config.generation_config import GenerationConfig
from core.interfaces.retriever import BaseRetriever, Document


class EmptyRetriever(BaseRetriever):
    def retrieve(self, embedding, top_k=3):
        return []

    def retrieve_with_scores(self, embedding, top_k=3):
        return []

    @property
    def index_dimension(self):
        return 10


class LowScoreRetriever(BaseRetriever):
    def retrieve(self, embedding, top_k=3):
        return [Document(content="Low relevance content", score=0.05)]

    def retrieve_with_scores(self, embedding, top_k=3):
        return [(Document(content="Low relevance content", score=0.05), 0.05)]

    @property
    def index_dimension(self):
        return 10


def test_failure_classifier_taxonomy():
    exc1 = ValueError("Embedding dimension mismatch with retriever index.")
    assert FailureClassifier.classify_exception(exc1, "init") == FailureType.DIMENSION_MISMATCH

    exc2 = ValueError("Context window exceeded before generation.")
    assert FailureClassifier.classify_exception(exc2, "token_budget") == FailureType.TOKEN_BUDGET_EXCEEDED

    exc3 = RuntimeError("Failed to generate response from model")
    assert FailureClassifier.classify_exception(exc3, "llm") == FailureType.LLM_FAILURE


def test_pipeline_tags_no_documents_retrieved():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        retriever=EmptyRetriever(),
        llm=DummyLLM(),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=CostTracker()
    )

    result = pipeline.run("Any query")
    assert FailureType.NO_DOCUMENTS_RETRIEVED.value in result["failure_tags"]


def test_pipeline_tags_low_retrieval_score():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        retriever=LowScoreRetriever(),
        llm=DummyLLM(),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=CostTracker(),
        similarity_threshold=0.5
    )

    result = pipeline.run("Any query")
    assert FailureType.LOW_RETRIEVAL_SCORE.value in result["failure_tags"]
