import pytest
from core.interfaces.retriever import Document
from core.implementations.simple_reranker import SimpleReranker, NoOpReranker
from app.pipeline import RAGPipeline
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService
from core.config.generation_config import GenerationConfig


def test_simple_reranker_reordering():
    reranker = SimpleReranker(initial_weight=0.2, lexical_weight=0.8)

    # doc1 has low lexical overlap with query, doc2 has high overlap
    docs = [
        Document(content="The weather is nice in spring.", score=0.9),
        Document(content="Quantum computing uses qubits and superposition.", score=0.5),
    ]

    query = "Quantum computing superposition"
    reranked = reranker.rerank(query, docs)

    assert len(reranked) == 2
    # Document 2 should now be ranked first due to lexical match
    assert "quantum" in reranked[0].content.lower()
    assert reranked[0].score > reranked[1].score
    assert "initial_score" in reranked[0].metadata
    assert "rerank_score" in reranked[0].metadata


def test_simple_reranker_with_scores():
    reranker = SimpleReranker()
    docs = [
        Document(content="Alpha beta gamma", score=0.8),
        Document(content="Delta epsilon", score=0.7)
    ]
    scored = reranker.rerank_with_scores("Alpha", docs, top_k=1)
    assert len(scored) == 1
    doc, score = scored[0]
    assert "Alpha" in doc.content
    assert isinstance(score, float)


def test_noop_reranker_preserves_order():
    reranker = NoOpReranker()
    docs = [
        Document(content="First doc", score=0.9),
        Document(content="Second doc", score=0.8)
    ]
    reranked = reranker.rerank("any query", docs)
    assert reranked[0].content == "First doc"
    assert reranked[1].content == "Second doc"


def test_reranker_in_pipeline():
    pipeline = RAGPipeline(
        embedder=DummyEmbedder(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        retriever=DummyRetriever(),
        llm=DummyLLM(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        evaluator=DummyEvaluator(),
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=CostTracker(),
        reranker=SimpleReranker()
    )

    result = pipeline.run("Dummy document 2")
    assert "retrieval_scores" in result
    assert "observability" in result
    assert result["observability"]["reranker"] == "SimpleReranker"
