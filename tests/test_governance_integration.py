import pytest

from core.services.cost_governor import CostGovernor
from core.services.failure_classifier import FailureType
from core.services.retrieval_policy_service import RetrievalPolicyService


def test_cost_governor_allows_request_within_limit(make_pipeline):
    pipeline = make_pipeline(cost_governor=CostGovernor(max_cost_per_request=1.0))
    result = pipeline.run("What is artificial intelligence?")
    assert result["response"] is not None
    assert result["failure_tags"] == []
    assert "estimated_cost_usd" in result["cost"]


def test_cost_governor_blocks_request_exceeding_limit(make_pipeline):
    pipeline = make_pipeline(
        cost_governor=CostGovernor(max_cost_per_request=0.0000001),
        raise_on_failure=False,
    )
    result = pipeline.run("What is machine learning?")
    assert result["failure_type"] == FailureType.COST_LIMIT_EXCEEDED.value
    assert FailureType.COST_LIMIT_EXCEEDED.value in result["failure_tags"]
    assert pipeline.last_failure == FailureType.COST_LIMIT_EXCEEDED.value


def test_cost_governor_raises_when_configured_to_fail(make_pipeline):
    pipeline = make_pipeline(cost_governor=CostGovernor(max_cost_per_request=0.0000001))
    with pytest.raises(ValueError) as exc_info:
        pipeline.run("What is machine learning?")
    assert getattr(exc_info.value, "failure_type", None) == FailureType.COST_LIMIT_EXCEEDED.value


def test_retrieval_policy_reduces_top_k(make_pipeline):
    restrictive_policy = RetrievalPolicyService(
        context_window=100,
        system_prompt_tokens=50,
        reserved_output_tokens=100,
        safety_margin=200,
    )
    pipeline = make_pipeline(retrieval_policy_service=restrictive_policy)
    result = pipeline.run("How many neural network documents are retrieved?")
    assert result["observability"]["top_k"] == 1
    assert len(result["retrieved_docs"]) <= 1


def test_retrieval_policy_failure_is_classified(make_pipeline):
    class BrokenPolicy:
        def compute_top_k(self, query_tokens: int, avg_chunk_tokens: int) -> int:
            raise ValueError("Invalid chunk size")

    pipeline = make_pipeline(retrieval_policy_service=BrokenPolicy(), raise_on_failure=False)
    result = pipeline.run("Trigger retrieval policy failure")
    assert result["failure_type"] == FailureType.RETRIEVAL_POLICY_FAILURE.value


def test_pipeline_without_governance_still_works(make_pipeline):
    pipeline = make_pipeline()
    result = pipeline.run("What is deep learning?")
    assert result["response"] is not None
    assert result["failure_tags"] == []
