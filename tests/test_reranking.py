from core.implementations.simple_reranker import SimpleReranker
from core.interfaces.retriever import Document


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


def test_simple_reranker_promotes_lexically_relevant_document():
    query = "Explain quantum computing qubits"
    candidates = [
        Document(content="Unrelated filler text about gardening.", score=0.88),
        Document(content="Quantum computing uses qubits and superposition principles.", score=0.72),
    ]
    reranker = SimpleReranker(strategy="lexical", top_k=2)

    reranked = reranker.rerank(query, candidates)

    assert "Quantum computing" in reranked[0].content
    assert reranked[0].metadata["final_rank"] == 0


def test_cross_encoder_reranker_promotes_relevant_document(real_reranker):
    query = "How do neural networks and deep learning work?"
    candidates = [
        Document(content="Cafeteria menu for Tuesday afternoon."),
        Document(content="Neural networks and deep learning architectures inspired by the human brain."),
        Document(content="Corporate travel reimbursement policy."),
    ]

    scored = real_reranker.rerank_with_scores(query, candidates, top_k=2)

    assert len(scored) == 2
    assert "Neural networks and deep learning" in scored[0].document.content
    assert scored[0].score > scored[1].score
    assert scored[0].document.metadata["reranker"] == "CrossEncoderReranker"


def test_reranker_integrated_in_rag_pipeline(make_pipeline, real_reranker):
    docs = [
        {"content": "Unrelated filler text about gardening and travel."},
        {"content": "Quantum computing uses qubits and superposition principles."},
        {"content": "Cafeteria menu for the week."},
    ]
    pipeline = make_pipeline(docs=docs, reranker=real_reranker, top_k=3)

    result = pipeline.run("Explain quantum computing qubits")

    assert "Quantum computing uses qubits" in result["retrieved_docs"][0]
    assert result["observability"]["reranker"] == "CrossEncoderReranker"
    assert result["observability"]["reranking_enabled"] is True


def test_reranking_ordering_differs_from_initial_retrieval(make_pipeline, real_reranker):
    docs = [
        {"content": "Cafeteria menu for Tuesday afternoon."},
        {"content": "Quantum computing relies on qubits and superposition."},
    ]
    pipeline = make_pipeline(docs=docs, reranker=real_reranker)

    result = pipeline.run("What are qubits in quantum computing?")

    observability = result["observability"]
    assert observability["initial_retrieved_documents"]
    assert observability["final_document_ordering"]
    assert observability["initial_retrieval_scores"] != result["retrieval_scores"]
