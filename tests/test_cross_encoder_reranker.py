import pytest

from core.implementations.cross_encoder_reranker import CrossEncoderReranker
from core.interfaces.retriever import Document


@pytest.fixture(scope="module")
def reranker():
    return CrossEncoderReranker()


def test_reorders_relevant_document_first(reranker):
    docs = [
        Document(content="Bananas are yellow and rich in potassium."),
        Document(content="Artificial intelligence simulates human intelligence in machines."),
        Document(content="The Eiffel Tower is located in Paris, France."),
    ]
    ranked = reranker.rerank("What is artificial intelligence?", docs)
    assert ranked[0].content.startswith("Artificial intelligence")
    assert ranked[0].score > ranked[-1].score


def test_rerank_with_scores_populates_metadata(reranker):
    docs = [
        Document(content="AI is the simulation of intelligence."),
        Document(content="Cats are common domestic mammals."),
    ]
    scored = reranker.rerank_with_scores("What is AI?", docs)
    top = scored[0]
    assert top.document.metadata["final_rank"] == 0
    assert top.document.metadata["reranker"] == "CrossEncoderReranker"
    assert scored[0].score > scored[1].score


def test_top_k_limits_results(reranker):
    docs = [Document(content=f"document number {i}") for i in range(5)]
    ranked = reranker.rerank("document", docs, top_k=2)
    assert len(ranked) == 2


def test_empty_documents_returns_empty(reranker):
    assert reranker.rerank("query", []) == []


def test_registry_builds_cross_encoder():
    from core.registry.reranker_registry import RerankerRegistry

    registry = RerankerRegistry()
    built = registry.create(name="cross_encoder")
    assert isinstance(built, CrossEncoderReranker)
