import pytest
from core.interfaces.retriever import Document
from core.implementations.simple_embedder import SimpleEmbedder
from core.implementations.faiss_retriever import FAISSRetriever


def test_faiss_retriever_initialization_and_search():
    embedder = SimpleEmbedder(model_name="sentence-transformers/all-MiniLM-L6-v2")
    retriever = FAISSRetriever(embedder=embedder)

    docs = [
        {"content": "Python is a high-level programming language.", "category": "tech"},
        {"content": "The Eiffel Tower is located in Paris.", "category": "travel"},
        {"content": "Photosynthesis is used by plants to generate oxygen.", "category": "science"}
    ]

    retriever.add_documents(docs)
    assert retriever.total_documents == 3
    assert retriever.index_dimension == 384

    query_emb = embedder.embed("Python programming coding")
    results = retriever.retrieve_with_scores(query_emb, top_k=2)

    assert len(results) == 2
    top_doc, top_score = results[0]
    assert isinstance(top_doc, Document)
    assert "Python" in top_doc.content
    assert top_doc.metadata.get("category") == "tech"
    assert top_score > 0
    assert top_doc.score == top_score


def test_faiss_retriever_retrieve_contract():
    embedder = SimpleEmbedder()
    retriever = FAISSRetriever(embedder=embedder)
    retriever.add_documents(["Doc 1", "Doc 2", "Doc 3"])

    docs = retriever.retrieve(embedder.embed("Doc 1"), top_k=2)
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_faiss_retriever_clear():
    embedder = SimpleEmbedder()
    retriever = FAISSRetriever(embedder=embedder)
    retriever.add_documents(["Alpha", "Beta"])
    assert retriever.total_documents == 2

    retriever.clear()
    assert retriever.total_documents == 0
    assert len(retriever.retrieve(embedder.embed("Alpha"), top_k=2)) == 0
