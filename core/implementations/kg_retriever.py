"""Knowledge-graph retriever provider (issue #24).

This is a deliberately small, dependency-free "triple store" retriever. It loads
subject–predicate–object triples from config or ``data/`` and exposes them through
the standard ``BaseRetriever`` contract by rendering each triple as a sentence and
reusing the embedding-cosine retrieval of :class:`SimpleRetriever`.

Because the ``BaseRetriever`` contract only receives a query *embedding*, the
retriever embeds the rendered triples (not the query text) and ranks them by
cosine similarity. An optional one-hop expansion then pulls in triples that share
an entity (subject/object) with the top-ranked triples, which improves recall for
relationship/multi-hop style queries that vector search handles poorly.

Selecting it is a config change:

    retrieval:
      default_retriever: kg
      retrievers:
        kg:
          provider: kg
          graph_path: data/knowledge_graph.json
          expansion_hops: 1
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.implementations.simple_retriever import SimpleRetriever
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument
from core.services.acl import normalize_acl_metadata


def _triple_to_document(triple: Dict[str, Any], doc_id: int) -> Document:
    subject = str(triple.get("subject", "")).strip()
    predicate = str(triple.get("predicate", "")).strip()
    obj = str(triple.get("object", "")).strip()
    content = f"{subject} {predicate} {obj}".strip()
    metadata: Dict[str, Any] = {
        "doc_id": doc_id,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "source": "knowledge_graph",
    }
    # Carry ACL fields attached to a triple (issue #51).
    for key in (
        "allowed_tenants",
        "allowed_users",
        "allowed_groups",
        "allowed_roles",
        "tenant_id",
        "tenant",
        "acl",
    ):
        if key in triple:
            metadata[key] = triple[key]
    return Document(
        content=content,
        metadata=normalize_acl_metadata(metadata),
    )


class KGRetriever(BaseRetriever):
    """Embedding-cosine retrieval over rendered knowledge-graph triples."""

    def __init__(
        self,
        docs: Optional[Sequence[Any]] = None,
        embedder: Any = None,
        triples: Optional[Sequence[Dict[str, Any]]] = None,
        graph_path: Optional[str] = None,
        expansion_hops: int = 0,
        max_expansion: int = 3,
        **_ignored: Any,
    ):
        if embedder is None:
            raise ValueError("The 'kg' retriever requires an embedder.")

        self.embedder = embedder
        self.expansion_hops = int(expansion_hops or 0)
        self.max_expansion = int(max_expansion)

        raw_triples = list(triples) if triples else []
        if not raw_triples and graph_path:
            raw_triples = self._load_graph(graph_path)
        if not raw_triples and docs:
            raw_triples = self._triples_from_docs(docs)

        self.triples: List[Dict[str, Any]] = [
            t for t in raw_triples if isinstance(t, dict)
        ]
        self._documents = [
            _triple_to_document(triple, idx) for idx, triple in enumerate(self.triples)
        ]
        # Reuse the well-tested embedding cosine ranking from SimpleRetriever.
        self._base = SimpleRetriever(docs=self._documents, embedder=embedder)
        # Entity -> triple indices, used for one-hop expansion.
        self._by_entity: Dict[str, List[int]] = {}
        for idx, triple in enumerate(self.triples):
            for entity in (triple.get("subject"), triple.get("object")):
                if entity:
                    self._by_entity.setdefault(str(entity).strip().lower(), []).append(idx)

    # -- loading ---------------------------------------------------------

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _load_graph(self, graph_path: str) -> List[Dict[str, Any]]:
        path = Path(graph_path)
        if not path.is_absolute():
            path = self._repo_root() / path
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and "triples" in data:
            data = data["triples"]
        if not isinstance(data, list):
            raise ValueError(
                f"Knowledge-graph file '{path}' must contain a list of triples."
            )
        return data

    @staticmethod
    def _triples_from_docs(docs: Sequence[Any]) -> List[Dict[str, Any]]:
        """Treat plain documents as unary triples so the provider still works."""
        triples: List[Dict[str, Any]] = []
        for doc in docs:
            content = doc.get("content") if isinstance(doc, dict) else str(doc)
            triples.append({"subject": str(content), "predicate": "text", "object": ""})
        return triples

    # -- BaseRetriever contract -----------------------------------------

    @property
    def index_dimension(self) -> int:
        return self._base.index_dimension

    def retrieve_with_scores(self, query_embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        base_hits = self._base.retrieve_with_scores(query_embedding, top_k=top_k)
        if self.expansion_hops <= 0 or not base_hits:
            return base_hits

        seen = {hit.metadata.get("doc_id") for hit in base_hits}
        expanded: List[ScoredDocument] = list(base_hits)
        frontier = list(base_hits)
        for _hop in range(self.expansion_hops):
            next_frontier: List[ScoredDocument] = []
            for hit in frontier:
                for entity in (
                    hit.metadata.get("subject"),
                    hit.metadata.get("object"),
                ):
                    if not entity:
                        continue
                    for idx in self._by_entity.get(str(entity).strip().lower(), []):
                        if idx in seen:
                            continue
                        seen.add(idx)
                        # Related triples inherit a slightly discounted score.
                        discount = round(float(hit.score or 0.0) * 0.5, 6)
                        related = ScoredDocument(
                            document=Document(
                                content=self._documents[idx].content,
                                metadata=dict(self._documents[idx].metadata),
                                score=discount,
                            ),
                            score=discount,
                        )
                        related.metadata["expansion"] = True
                        expanded.append(related)
                        next_frontier.append(related)
                        if len(expanded) >= top_k + self.max_expansion:
                            break
                    if len(expanded) >= top_k + self.max_expansion:
                        break
                if len(expanded) >= top_k + self.max_expansion:
                    break
            if len(expanded) >= top_k + self.max_expansion:
                break
            frontier = next_frontier

        return expanded

    def retrieve(self, query_embedding: List[float], top_k: int = 3) -> List[Document]:
        return [item.document for item in self.retrieve_with_scores(query_embedding, top_k=top_k)]
