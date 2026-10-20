"""Tests for issue #24: knowledge-graph retriever provider.

Covers the ``KGRetriever`` implementation (BaseRetriever contract, triple
rendering, one-hop expansion) and its registration/selection through
``RetrieverRegistry`` and the composition root.
"""

import json

import yaml

from core.implementations.kg_retriever import KGRetriever
from core.interfaces.retriever import Document, ScoredDocument
from core.registry.retriever_registry import RetrieverRegistry

TRIPLES = [
    {"subject": "Machine Learning", "predicate": "is_a", "object": "Artificial Intelligence"},
    {"subject": "Deep Learning", "predicate": "is_a", "object": "Machine Learning"},
    {"subject": "Deep Learning", "predicate": "uses", "object": "Neural Networks"},
    {"subject": "Neural Networks", "predicate": "inspired_by", "object": "Human Brain"},
]


class _Embedder:
    """Deterministic bag-of-words embedder (no model downloads)."""

    dimension = 12

    def embed(self, text):
        vec = [0.0] * self.dimension
        for token in str(text).lower().split():
            vec[hash(token) % self.dimension] += 1.0
        return vec


# -- implementation --------------------------------------------------------


def test_kg_retriever_implements_base_contract():
    retriever = KGRetriever(triples=TRIPLES, embedder=_Embedder())
    assert isinstance(retriever, KGRetriever)
    assert retriever.index_dimension == 12
    result = retriever.retrieve_with_scores(_Embedder().embed("deep learning"), top_k=2)
    assert result and all(isinstance(item, ScoredDocument) for item in result)
    docs = retriever.retrieve(_Embedder().embed("deep learning"), top_k=2)
    assert all(isinstance(doc, Document) for doc in docs)


def test_kg_retriever_renders_triples_as_documents():
    retriever = KGRetriever(triples=TRIPLES, embedder=_Embedder())
    contents = [doc.content for doc in retriever._documents]
    assert "Deep Learning is_a Machine Learning" in contents
    first = retriever._documents[0]
    assert first.metadata["subject"] == "Machine Learning"
    assert first.metadata["predicate"] == "is_a"
    assert first.metadata["object"] == "Artificial Intelligence"
    assert first.metadata["doc_id"] == 0
    assert first.metadata["source"] == "knowledge_graph"


def test_kg_retriever_requires_embedder():
    try:
        KGRetriever(triples=TRIPLES, embedder=None)
    except ValueError as exc:
        assert "embedder" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_kg_retriever_loads_graph_from_path(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"triples": TRIPLES}), encoding="utf-8")
    retriever = KGRetriever(graph_path=str(graph), embedder=_Embedder())
    assert len(retriever.triples) == len(TRIPLES)


def test_kg_one_hop_expansion_pulls_related_triples():
    retriever = KGRetriever(triples=TRIPLES, embedder=_Embedder(), expansion_hops=1, max_expansion=2)
    hits = retriever.retrieve_with_scores(_Embedder().embed("Deep Learning"), top_k=1)
    # top_k=1 base hit + at least one related triple via the shared entity.
    assert len(hits) > 1
    assert any(hit.metadata.get("expansion") for hit in hits)


def test_kg_without_expansion_returns_only_base_hits():
    retriever = KGRetriever(triples=TRIPLES, embedder=_Embedder(), expansion_hops=0)
    hits = retriever.retrieve_with_scores(_Embedder().embed("Deep Learning"), top_k=2)
    assert len(hits) == 2
    assert all(not hit.metadata.get("expansion") for hit in hits)


# -- registry / composition wiring ----------------------------------------


def _write_retrieval_config(tmp_path, retrievers, default="kg"):
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


def test_registry_registers_kg_provider(tmp_path):
    registry = RetrieverRegistry(_write_retrieval_config(tmp_path, {"kg": {"provider": "kg"}}))
    assert "kg" in registry.list_providers()
    assert "kg" in registry.list_retrievers()


def test_registry_builds_kg_retriever_from_config(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"triples": TRIPLES}), encoding="utf-8")
    config = _write_retrieval_config(
        tmp_path,
        {"kg": {"provider": "kg", "graph_path": str(graph), "expansion_hops": 1}},
    )
    retriever = RetrieverRegistry(config).create(embedder=_Embedder())
    assert isinstance(retriever, KGRetriever)
    assert len(retriever.triples) == len(TRIPLES)
    assert retriever.expansion_hops == 1


def test_registry_kg_requires_embedder(tmp_path):
    config = _write_retrieval_config(tmp_path, {"kg": {"provider": "kg"}})
    try:
        RetrieverRegistry(config).create()
    except ValueError as exc:
        assert "embedder" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
