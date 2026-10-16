import pytest

from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.faiss_retriever import FAISSRetriever
from core.implementations.simple_embedder import SimpleEmbedder
from core.implementations.simple_retriever import SimpleRetriever
from core.interfaces.retriever import Document, ScoredDocument


def test_simple_retriever_returns_similarity_scores():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Quantum physics studies subatomic particles and wave functions."},
    ]
    embedder = SimpleEmbedder(model_name="all-MiniLM-L6-v2")
    retriever = SimpleRetriever(docs=docs, embedder=embedder)

    query_emb = embedder.embed("What is Artificial Intelligence?")
    scored_docs = retriever.retrieve_with_scores(query_emb, top_k=2)

    assert len(scored_docs) == 2
    assert isinstance(scored_docs[0], ScoredDocument)
    assert isinstance(scored_docs[0].document, Document)
    assert scored_docs[0].score >= scored_docs[1].score
    assert "Artificial Intelligence" in scored_docs[0].content

    # Verify tuple unpacking and key access
    doc_obj, score_val = scored_docs[0]
    assert doc_obj.content == scored_docs[0].content
    assert score_val == scored_docs[0].score
    assert scored_docs[0]["score"] == score_val


def test_faiss_retriever_index_creation_insertion_querying_and_mapping():
    docs = [
        {"content": "Neural networks are models inspired by the human brain.", "metadata": {"topic": "nn"}},
        {"content": "Deep learning uses multi-layer neural networks.", "metadata": {"topic": "dl"}},
        {"content": "Financial accounting tracks corporate balance sheets.", "metadata": {"topic": "finance"}},
    ]
    embedder = SimpleEmbedder(model_name="all-MiniLM-L6-v2")
    faiss_retriever = FAISSRetriever(docs=docs, embedder=embedder)

    assert faiss_retriever.index_dimension == 384
    assert faiss_retriever.total_documents == 3

    # Add an additional document dynamically
    added = faiss_retriever.add_documents(
        [Document(content="Brain neurons inspire artificial neural network architectures.", metadata={"topic": "neuro"})]
    )
    assert added == 1
    assert faiss_retriever.total_documents == 4

    query_emb = embedder.embed("How do neural networks relate to the human brain?")
    results_with_scores = faiss_retriever.retrieve_with_scores(query_emb, top_k=3)

    assert len(results_with_scores) == 3
    for item in results_with_scores:
        assert isinstance(item, ScoredDocument)
        assert isinstance(item.document, Document)
        assert item.score is not None
        assert "faiss_id" in item.metadata

    # Verify scores are ordered descending
    assert results_with_scores[0].score >= results_with_scores[1].score >= results_with_scores[2].score

    # Verify standard retrieve() contract still returns List[Document] with score metadata
    plain_docs = faiss_retriever.retrieve(query_emb, top_k=2)
    assert len(plain_docs) == 2
    assert all(isinstance(d, Document) for d in plain_docs)
    assert all(d.score is not None for d in plain_docs)


def test_faiss_retriever_negative_scenarios():
    embedder = DummyEmbedder(dimension=10)
    retriever = FAISSRetriever(embedder=embedder)

    # Empty index returns empty list without crashing
    assert retriever.retrieve([0.1] * 10, top_k=3) == []

    # Query dimension mismatch raises ValueError
    retriever.add_documents([{"content": "Sample doc"}])
    with pytest.raises(ValueError):
        retriever.retrieve([0.1] * 5, top_k=1)

    # Document embedding dimension mismatch raises ValueError
    with pytest.raises(ValueError):
        retriever.add_documents([{"content": "Bad dim doc"}], embeddings=[[0.1, 0.2]])

    # Missing both embedder and dimension raises ValueError
    with pytest.raises(ValueError):
        FAISSRetriever(docs=None, embedder=None, dimension=None)

    # Invalid dimension <= 0 raises ValueError
    with pytest.raises(ValueError):
        FAISSRetriever(dimension=0)


def test_dummy_retriever_exposes_scores():
    retriever = DummyRetriever()
    scored = retriever.retrieve_with_scores([0.1] * 10, top_k=2)
    assert len(scored) == 2
    assert scored[0].score == 0.91
    assert scored[1].score == 0.84
