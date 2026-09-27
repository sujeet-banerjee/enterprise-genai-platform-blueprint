from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.simple_reranker import SimpleReranker
from core.interfaces.retriever import Document
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


def test_simple_reranker_changes_document_ordering():
    # Document 0 has a higher initial score (0.90) but no lexical overlap with query;
    # Document 1 has slightly lower initial score (0.75) but strong lexical overlap with query.
    candidates = [
        Document(content="General corporate policy on office holidays and travel.", score=0.90),
        Document(content="Neural networks and deep learning architectures inspired by the human brain.", score=0.75),
        Document(content="Cafeteria menu for Tuesday afternoon.", score=0.60),
    ]

    reranker = SimpleReranker(strategy="lexical_hybrid", lexical_weight=0.8, initial_score_weight=0.2)
    reranked = reranker.rerank(
        query="How do neural networks and deep learning work?",
        documents=candidates,
    )

    assert len(reranked) == 3
    assert "Neural networks and deep learning" in reranked[0].content
    assert reranked[0].metadata["initial_rank"] == 1
    assert reranked[0].metadata["final_rank"] == 0
    assert reranked[0].score > reranked[1].score


def test_reranker_custom_scoring_callable_and_top_k():
    candidates = [
        Document(content="Short text", score=0.9),
        Document(content="Much longer document content that should win under length scorer", score=0.4),
        Document(content="Medium document content", score=0.6),
    ]

    # Pluggable custom scorer (simulating cross-encoder or external API)
    custom_reranker = SimpleReranker(scoring_fn=lambda q, d: float(len(d.content)))
    top2 = custom_reranker.rerank("any query", candidates, top_k=2)

    assert len(top2) == 2
    assert "Much longer document" in top2[0].content
    assert "Medium document" in top2[1].content


def test_reranker_integrated_in_rag_pipeline():
    docs = [
        Document(content="Unrelated filler text about gardening.", score=0.88),
        Document(content="Quantum computing uses qubits and superposition principles.", score=0.72),
    ]
    retriever = DummyRetriever(docs=docs, dimension=10)
    reranker = SimpleReranker(strategy="lexical", top_k=2)

    pipeline = RAGPipeline(
        embedder=DummyEmbedder(dimension=10),
        retriever=retriever,
        llm=DummyLLM(),
        prompt_builder=PromptBuilder("config/prompt_config.yaml"),
        evaluator=DummyEvaluator(),
        token_budget_service=TokenBudgetService(policy_mode="strict"),
        generation_config=GenerationConfig(max_tokens=256),
        cost_tracker=CostTracker(),
        reranker=reranker,
    )

    result = pipeline.run("Explain quantum computing qubits")
    assert "Quantum computing uses qubits" in result["retrieved_docs"][0]
    assert result["observability"]["reranker"] == "SimpleReranker"
