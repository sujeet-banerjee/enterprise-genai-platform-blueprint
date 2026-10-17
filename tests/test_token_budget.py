import pytest

from core.interfaces.retriever import Document
from core.services.token_budget_service import TokenBudgetExceededError, TokenBudgetService


def test_token_budget_reduces_output(make_pipeline):
    pipeline = make_pipeline(max_tokens=100)

    result = pipeline.run("Short question?")

    assert result["response"]
    assert result["token_budget"]["allowed_output_tokens"] <= 100
    assert result["token_budget"]["budget_mode"] == "strict"


def test_token_budget_strict_mode_exact_calculation():
    service = TokenBudgetService(policy_mode="strict")
    result = service.compute_budget(
        context_window=1000,
        system_prompt_tokens=100,
        user_query_tokens=50,
        retrieved_context_tokens=550,
        requested_max_output_tokens=400,
    )
    assert result["available_output_tokens"] == 300
    assert result["allowed_output_tokens"] == 300
    assert result["budget_mode"] == "strict"
    assert result["documents_removed"] == 0
    assert result["fits_context_window"] is True


def test_token_budget_strict_mode_raises_when_exceeded():
    service = TokenBudgetService(policy_mode="strict")
    with pytest.raises(TokenBudgetExceededError) as exc_info:
        service.compute_budget(
            context_window=200,
            system_prompt_tokens=80,
            user_query_tokens=50,
            retrieved_context_tokens=100,
            requested_max_output_tokens=50,
        )
    assert exc_info.value.failure_type == "token_budget_exceeded"


def test_token_budget_truncate_mode_removes_and_truncates_low_priority_docs():
    service = TokenBudgetService(policy_mode="truncate")
    docs = [
        Document(content="High priority context. " * 10, score=0.95),
        Document(content="Medium priority context. " * 10, score=0.75),
        Document(content="Lowest priority context. " * 20, score=0.20),
    ]
    result = service.compute_budget(
        query="What is the priority?",
        retrieved_docs=docs,
        system_prompt="You are a helpful assistant.",
        context_window=180,
        requested_max_tokens=40,
    )
    assert result["budget_mode"] == "truncate"
    assert result["final_context_tokens"] < result["original_context_tokens"]
    assert result["documents_removed_or_truncated"] >= 1
    assert result["allowed_output_tokens"] > 0
    assert len(result["retained_docs"]) <= len(docs)
    # Highest priority document should be preserved first
    assert "High priority context." in result["retained_docs"][0].content


def test_token_budget_truncate_mode_end_to_end(make_pipeline):
    pipeline = make_pipeline(policy_mode="truncate", max_tokens=64)

    result = pipeline.run("What is machine learning?")

    assert result["response"]
    assert result["token_budget"]["budget_mode"] == "truncate"
    assert result["token_budget"]["final_context_tokens"] <= result["token_budget"]["original_context_tokens"]
    assert result["failure_tags"] == []


def test_token_budget_invalid_mode_raises():
    with pytest.raises(ValueError):
        TokenBudgetService(policy_mode="invalid_mode")
