import pytest
from core.interfaces.retriever import Document
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.simple_retriever import SimpleRetriever
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.simple_embedder import SimpleEmbedder


def test_document_score_initialization():
    doc = Document(content="Sample content", score=0.88)
    assert doc.content == "Sample content"
    assert doc.score == 0.88
    assert doc.metadata.get("score") == 0.88


def test_dummy_retriever_retrieve_with_scores():
    retriever = DummyRetriever()
    results = retriever.retrieve_with_scores([0.1] * 10, top_k=2)

    assert len(results) == 2
    for doc, score in results:
        assert isinstance(doc, Document)
        assert isinstance(score, float)
        assert doc.score == score
        assert score > 0


def test_simple_retriever_retrieve_with_scores():
    embedder = SimpleEmbedder()
    docs = [
        {"content": "Python is a programming language."},
        {"content": "Deep learning models are trained on GPUs."},
        {"content": "Paris is the capital of France."}
    ]
    retriever = SimpleRetriever(docs=docs, embedder=embedder)

    query_emb = embedder.embed("Python programming")
    scored_results = retriever.retrieve_with_scores(query_emb, top_k=2)

    assert len(scored_results) == 2
    top_doc, top_score = scored_results[0]
    assert isinstance(top_doc, Document)
    assert isinstance(top_score, float)
    assert "python" in top_doc.content.lower()

    # Scores should be sorted in descending order
    scores = [s for _, s in scored_results]
    assert scores == sorted(scores, reverse=True)


def test_retriever_backward_compatibility():
    embedder = DummyEmbedder()
    docs = [{"content": "Doc A"}, {"content": "Doc B"}]
    retriever = SimpleRetriever(docs=docs, embedder=embedder)

    docs_only = retriever.retrieve(embedder.embed("test"), top_k=2)
    assert len(docs_only) == 2
    assert all(isinstance(d, Document) for d in docs_only)
