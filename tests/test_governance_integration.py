import pytest

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_retriever import DummyRetriever
from core.services.cost_governor import CostGovernor
from core.services.cost_tracker import CostTracker
from core.services.failure_classifier import FailureType
from core.services.prompt_builder import PromptBuilder
from core.services.retrieval_policy_service import RetrievalPolicyService
from core.services.token_budget_service import TokenBudgetService


def build_pipeline(cost_governor=None, retrieval_policy_service=None, raise_on_failure=True):
    return RAGPipeline(
        embedder=DummyEmbedder(),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
        cost_governor=cost_governor,
        retrieval_policy_service=retrieval_policy_service,
        raise_on_failure=raise_on_failure,
    )


def test_cost_governor_allows_request_within_limit():
    pipeline = build_pipeline(cost_governor=CostGovernor(max_cost_per_request=1.0))
    result = pipeline.run("What is the refund policy?")
    assert result["response"] is not None
    assert result["failure_tags"] == []
    assert "estimated_cost_usd" in result["cost"]


def test_cost_governor_blocks_request_exceeding_limit():
    # Dummy cost is 0.001 USD; a near-zero ceiling must trip the governor.
    pipeline = build_pipeline(
        cost_governor=CostGovernor(max_cost_per_request=0.0000001),
        raise_on_failure=False,
    )
    result = pipeline.run("Expensive enterprise query")
    assert result["failure_type"] == FailureType.COST_LIMIT_EXCEEDED.value
    assert FailureType.COST_LIMIT_EXCEEDED.value in result["failure_tags"]
    assert pipeline.last_failure == FailureType.COST_LIMIT_EXCEEDED.value


def test_cost_governor_raises_when_configured_to_fail():
    pipeline = build_pipeline(cost_governor=CostGovernor(max_cost_per_request=0.0000001))
    with pytest.raises(ValueError) as exc_info:
        pipeline.run("Expensive enterprise query")
    assert getattr(exc_info.value, "failure_type", None) == FailureType.COST_LIMIT_EXCEEDED.value


def test_retrieval_policy_reduces_top_k():
    restrictive_policy = RetrievalPolicyService(
        context_window=100,
        system_prompt_tokens=50,
        reserved_output_tokens=100,
        safety_margin=200,
    )
    pipeline = build_pipeline(retrieval_policy_service=restrictive_policy)
    result = pipeline.run("How many documents are retrieved?")
    assert result["observability"]["top_k"] == 1
    assert len(result["retrieved_docs"]) <= 1


def test_retrieval_policy_failure_is_classified():
    class BrokenPolicy:
        def compute_top_k(self, query_tokens: int, avg_chunk_tokens: int) -> int:
            raise ValueError("Invalid chunk size")

    pipeline = build_pipeline(retrieval_policy_service=BrokenPolicy(), raise_on_failure=False)
    result = pipeline.run("Trigger retrieval policy failure")
    assert result["failure_type"] == FailureType.RETRIEVAL_POLICY_FAILURE.value


def test_pipeline_without_governance_still_works():
    pipeline = build_pipeline()
    result = pipeline.run("No governance configured")
    assert result["response"] is not None
    assert result["failure_tags"] == []
