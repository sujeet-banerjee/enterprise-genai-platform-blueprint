import pytest
from core.interfaces.retriever import Document
from core.services.token_budget_service import TokenBudgetService


def test_strict_mode_within_budget():
    service = TokenBudgetService(policy_mode="strict", max_output_cap=512)
    docs = [
        Document(content="Short document text.", score=0.9)
    ]

    budget = service.compute_budget(
        query="What is this?",
        retrieved_docs=docs,
        system_prompt="You are helpful.",
        context_window=1000,
        requested_max_tokens=256
    )

    assert budget["budget_mode"] == "strict"
    assert budget["allowed_output_tokens"] == 256
    assert budget["documents_removed"] == 0
    assert budget["original_context_tokens"] == budget["final_context_tokens"]
    assert budget["remaining_budget"] > 0


def test_strict_mode_exceeds_context_window():
    service = TokenBudgetService(policy_mode="strict")
    docs = [
        Document(content="A" * 800)  # ~200 tokens
    ]

    # Context window of only 50 tokens cannot fit 200 tokens
    with pytest.raises(ValueError) as exc_info:
        service.compute_budget(
            query="Short query",
            retrieved_docs=docs,
            system_prompt="System prompt",
            context_window=50,
            requested_max_tokens=100
        )
    assert "Context window exceeded" in str(exc_info.value)


def test_truncate_mode_removes_low_priority_documents():
    service = TokenBudgetService(policy_mode="truncate", max_output_cap=512)

    # 3 docs: High score, Medium score, Low score
    docs = [
        Document(content="A" * 100, score=0.9),  # 25 tokens
        Document(content="B" * 100, score=0.5),  # 25 tokens
        Document(content="C" * 100, score=0.1),  # 25 tokens
    ]

    # Context window is 80 tokens.
    # Fixed tokens: query (5 tokens) + sys (5 tokens) = 10 tokens.
    # Target output = 40 tokens.
    # Total available for docs = 80 - 10 - 40 = 30 tokens.
    # Only 1 doc (25 tokens) should fit!
    budget = service.compute_budget(
        query="Query test",
        retrieved_docs=docs,
        system_prompt="Sys prompt",
        context_window=80,
        requested_max_tokens=40
    )

    assert budget["budget_mode"] == "truncate"
    assert budget["documents_removed"] >= 1
    assert len(budget["retained_docs"]) < len(docs)
    assert budget["final_context_tokens"] < budget["original_context_tokens"]
    assert budget["allowed_output_tokens"] > 0
    # Highest priority doc should be kept
    assert budget["retained_docs"][0].score == 0.9


def test_truncate_mode_fails_if_fixed_tokens_exceed_window():
    service = TokenBudgetService(policy_mode="truncate")
    with pytest.raises(ValueError):
        service.compute_budget(
            query="A" * 400,  # 100 tokens
            retrieved_docs=[],
            system_prompt="B" * 400,  # 100 tokens
            context_window=50,
            requested_max_tokens=20
        )
