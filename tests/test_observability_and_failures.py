import pytest

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.simple_reranker import SimpleReranker
from core.interfaces.retriever import Document
from core.services.cost_tracker import CostTracker
from core.services.failure_classifier import FailureType
from core.services.observability import SensitiveDataRedactor
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


def test_pipeline_stage_latency_and_observability_fields():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
        reranker=SimpleReranker(),
    )

    result = pipeline.run("What is enterprise RAG?")
    assert "latency" in result
    assert "observability" in result
    assert "retrieval_scores" in result

    latency = result["latency"]
    for stage in (
        "embedding",
        "retrieval",
        "reranking",
        "token_budget",
        "prompt_construction",
        "llm_generation",
        "evaluation",
        "total_pipeline",
    ):
        assert stage in latency
        assert isinstance(latency[stage], float)
        assert latency[stage] >= 0.0

    obs = result["observability"]
    for expected_key in (
        "request_id",
        "query",
        "embedding_model",
        "embedding_dimension",
        "retriever",
        "top_k",
        "retrieved_documents",
        "retrieval_scores",
        "reranker",
        "final_document_ordering",
        "token_budget",
        "latency",
        "llm_model",
        "failure_tags",
    ):
        assert expected_key in obs


def test_sensitive_data_redaction_in_observability_logs():
    secret_doc = Document(
        content="Internal configuration: api_key=sk-proj1234567890abcdef password=MySuperSecretPassword123",
        score=0.92,
    )
    retriever = DummyRetriever(docs=[secret_doc], dimension=10)

    pipeline = RAGPipeline(
        embedder=DummyEmbedder(dimension=10),
        retriever=retriever,
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
    )

    result = pipeline.run("Check credentials api_key=sk-9999999999abcdef")
    obs_str = str(result["observability"])

    assert "sk-proj1234567890abcdef" not in obs_str
    assert "MySuperSecretPassword123" not in obs_str
    assert "sk-9999999999abcdef" not in obs_str
    assert "[REDACTED]" in obs_str
    assert "[REDACTED]" in SensitiveDataRedactor.redact_text("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")


def test_failure_classification_no_documents_and_low_retrieval_score():
    empty_retriever = DummyRetriever(docs=[], dimension=10)
    pipeline_empty = RAGPipeline(
        embedder=DummyEmbedder(dimension=10),
        retriever=empty_retriever,
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
    )
    res_empty = pipeline_empty.run("Query with no docs")
    assert FailureType.NO_DOCUMENTS_RETRIEVED.value in res_empty["failure_tags"]

    low_score_retriever = DummyRetriever(
        docs=[Document(content="Weakly related text", score=0.05)],
        dimension=10,
    )
    pipeline_low = RAGPipeline(
        embedder=DummyEmbedder(dimension=10),
        retriever=low_score_retriever,
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
    )
    res_low = pipeline_low.run("Query with low score")
    assert FailureType.LOW_RETRIEVAL_SCORE.value in res_low["failure_tags"]


def test_failure_classification_across_pipeline_exceptions():
    class FailingEmbedder(DummyEmbedder):
        def embed(self, text: str):
            raise RuntimeError("Embedding model crashed")

    pipeline_emb_fail = RAGPipeline(
        embedder=FailingEmbedder(),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
        raise_on_failure=False,
    )
    res_emb = pipeline_emb_fail.run("Test failure")
    assert res_emb["failure_type"] == FailureType.EMBEDDING_FAILURE.value
    assert FailureType.EMBEDDING_FAILURE.value in res_emb["failure_tags"]

    class FailingLLM(DummyLLM):
        def generate(self, prompt: str, config=None) -> str:
            raise RuntimeError("LLM provider timeout")

    pipeline_llm_fail = RAGPipeline(
        embedder=DummyEmbedder(),
        retriever=DummyRetriever(),
        llm=FailingLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
    )
    with pytest.raises(RuntimeError) as exc_info:
        pipeline_llm_fail.run("Test LLM failure")
    assert getattr(exc_info.value, "failure_type", None) == FailureType.LLM_FAILURE.value
    assert pipeline_llm_fail.last_failure == FailureType.LLM_FAILURE.value
