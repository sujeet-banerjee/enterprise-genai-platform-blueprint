"""Tests for issue #25: hybrid (keyword + vector) retriever provider.

Covers the ``HybridRetriever`` fusion logic (BM25 + vector, configurable weights,
determinism), its BaseRetriever contract, registry/config selection, and a
pipeline end-to-end run that passes the query text via ``retrieve_with_query``.
"""

import json

import yaml

from core.implementations.hybrid_retriever import HybridRetriever
from core.interfaces.retriever import Document, ScoredDocument
from core.registry.retriever_registry import RetrieverRegistry

DOCS = [
    {"content": "The product SKU-9981 is discontinued."},
    {"content": "General overview of product categories and catalogues."},
    {"content": "How to browse the online store and checkout."},
]


class _SemanticEmbedder:
    """Deterministic embedder whose vector signal ignores rare identifiers.

    It maps each known "topic" word to a dimension, but drops tokens containing a
    digit (so ``SKU-9981`` contributes nothing to the vector). This lets a test
    distinguish the vector signal from the lexical (BM25) signal.
    """

    dimension = 6
    _TOPICS = ["product", "store", "checkout", "catalogue", "browse", "categories"]

    def embed(self, text):
        vec = [0.0] * self.dimension
        for token in str(text).lower().split():
            if any(ch.isdigit() for ch in token):
                continue
            clean = token.strip(".,")
            if clean in self._TOPICS:
                vec[self._TOPICS.index(clean)] += 1.0
        return vec


def _contents(items):
    return [doc.content for doc in items]


# -- implementation --------------------------------------------------------


def test_hybrid_implements_base_contract():
    retriever = HybridRetriever(docs=DOCS, embedder=_SemanticEmbedder())
    assert retriever.index_dimension == 6
    scored = retriever.retrieve_with_scores(_SemanticEmbedder().embed("product"), top_k=2)
    assert scored and all(isinstance(item, ScoredDocument) for item in scored)
    docs = retriever.retrieve(_SemanticEmbedder().embed("product"), top_k=2)
    assert all(isinstance(doc, Document) for doc in docs)


def test_hybrid_requires_embedder():
    try:
        HybridRetriever(docs=DOCS, embedder=None)
    except ValueError as exc:
        assert "embedder" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_hybrid_keyword_weight_surfaces_exact_match():
    retriever = HybridRetriever(
        docs=DOCS, embedder=_SemanticEmbedder(), keyword_weight=1.0, vector_weight=0.0
    )
    embedder = _SemanticEmbedder()
    results = retriever.retrieve_with_query("SKU-9981", embedder.embed("SKU-9981"), top_k=3)
    # The doc containing the exact identifier must rank first.
    assert results[0].content == "The product SKU-9981 is discontinued."
    assert results[0].metadata["lexical_score"] > 0


def test_hybrid_vector_weight_surfaces_semantic_match():
    retriever = HybridRetriever(
        docs=DOCS, embedder=_SemanticEmbedder(), keyword_weight=0.0, vector_weight=1.0
    )
    embedder = _SemanticEmbedder()
    results = retriever.retrieve_with_query("browse store", embedder.embed("browse store"), top_k=1)
    # Pure vector: the browsing/checkout doc shares topic words -> ranks first.
    assert results[0].content == "How to browse the online store and checkout."


def test_hybrid_weights_change_ranking():
    embedder = _SemanticEmbedder()
    query = "store SKU-9981"
    embedding = embedder.embed(query)

    lexical_first = HybridRetriever(
        docs=DOCS, embedder=embedder, keyword_weight=1.0, vector_weight=0.0
    ).retrieve_with_query(query, embedding, top_k=3)
    vector_first = HybridRetriever(
        docs=DOCS, embedder=embedder, keyword_weight=0.0, vector_weight=1.0
    ).retrieve_with_query(query, embedding, top_k=3)

    assert lexical_first[0].content == "The product SKU-9981 is discontinued."
    assert vector_first[0].content == "How to browse the online store and checkout."
    assert lexical_first[0].content != vector_first[0].content


def test_hybrid_is_deterministic():
    embedder = _SemanticEmbedder()
    retriever = HybridRetriever(docs=DOCS, embedder=embedder)
    first = _contents(retriever.retrieve_with_query("product store", embedder.embed("product store"), 3))
    second = _contents(retriever.retrieve_with_query("product store", embedder.embed("product store"), 3))
    assert first == second


def test_hybrid_without_query_text_degrades_to_vector():
    retriever = HybridRetriever(docs=DOCS, embedder=_SemanticEmbedder())
    # retrieve_with_scores has no query text -> vector-only, still valid.
    scored = retriever.retrieve_with_scores(_SemanticEmbedder().embed("store"), top_k=2)
    assert len(scored) == 2
    assert all("lexical_score" not in item.metadata for item in scored)


# -- registry / config -----------------------------------------------------


def _write_retrieval_config(tmp_path, retrievers, default="hybrid"):
    path = tmp_path / "retrieval.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "retrieval": {
                    "default_retriever": default,
                    "top_k": 3,
                    "retrievers": retrievers,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return str(path)


def test_registry_registers_hybrid_provider(tmp_path):
    registry = RetrieverRegistry(_write_retrieval_config(tmp_path, {"hybrid": {"provider": "hybrid"}}))
    assert "hybrid" in registry.list_providers()
    assert "hybrid" in registry.list_retrievers()


def test_registry_builds_hybrid_with_weights_from_config(tmp_path):
    docs = tmp_path / "docs.json"
    docs.write_text(json.dumps(DOCS), encoding="utf-8")
    config = _write_retrieval_config(
        tmp_path,
        {
            "hybrid": {
                "provider": "hybrid",
                "documents_path": str(docs),
                "keyword_weight": 0.7,
                "vector_weight": 0.3,
            }
        },
    )
    retriever = RetrieverRegistry(config).create(embedder=_SemanticEmbedder())
    assert isinstance(retriever, HybridRetriever)
    assert retriever.keyword_weight == 0.7
    assert retriever.vector_weight == 0.3


def test_registry_hybrid_requires_embedder(tmp_path):
    config = _write_retrieval_config(tmp_path, {"hybrid": {"provider": "hybrid"}})
    try:
        RetrieverRegistry(config).create()
    except ValueError as exc:
        assert "embedder" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# -- pipeline integration --------------------------------------------------


def test_pipeline_passes_query_text_to_hybrid_retriever(make_pipeline):
    calls = {}

    class _RecordingHybrid(HybridRetriever):
        def retrieve_with_query(self, query, query_embedding, top_k=3):
            calls["query"] = query
            return super().retrieve_with_query(query, query_embedding, top_k=top_k)

    retriever = _RecordingHybrid(docs=DOCS, embedder=_SemanticEmbedder())
    pipeline = make_pipeline(retriever=retriever, embedder=_SemanticEmbedder(), reranker=None)
    result = pipeline.run("store SKU-9981", raise_on_failure=False)

    assert calls.get("query") == "store SKU-9981"
    assert "The product SKU-9981 is discontinued." in result["retrieved_docs"]

