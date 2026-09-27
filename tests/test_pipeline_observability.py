import pytest
from app.pipeline import RAGPipeline
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.simple_reranker import SimpleReranker
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService
from core.config.generation_config import GenerationConfig
from core.observability.structured_logger import sanitize_text


def test_pipeline_observability_and_latencies():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=CostTracker(),
        reranker=SimpleReranker()
    )

    result = pipeline.run("Test observability query")

    assert "latencies" in result
    latencies = result["latencies"]
    assert "embedding_ms" in latencies
    assert "retrieval_ms" in latencies
    assert "reranking_ms" in latencies
    assert "prompt_construction_ms" in latencies
    assert "llm_generation_ms" in latencies
    assert "evaluation_ms" in latencies
    assert "total_pipeline_ms" in latencies

    assert "observability" in result
    obs = result["observability"]
    assert obs["query"] == "Test observability query"
    assert "embedding_model" in obs
    assert "embedding_dimension" in obs
    assert "retriever" in obs
    assert "top_k" in obs
    assert "retrieved_documents" in obs
    assert "retrieval_scores" in obs
    assert "reranker" in obs
    assert "final_document_ordering" in obs
    assert "token_budget" in obs
    assert "llm_model" in obs


def test_sanitize_text_redacts_secrets():
    text_with_key = "Connecting with api_key: 'sk-1234567890abcdef12345678' and password='secretpassword123'"
    sanitized = sanitize_text(text_with_key)

    assert "sk-1234567890abcdef12345678" not in sanitized
    assert "secretpassword123" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized
