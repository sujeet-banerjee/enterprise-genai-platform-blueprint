import logging
from typing import Any, Optional, Sequence

from core.interfaces.retriever import Document


def _doc_id(doc: Any) -> Optional[Any]:
    """Best-effort stable identifier for a document (metadata ``doc_id``)."""
    metadata = getattr(doc, "metadata", None)
    if isinstance(metadata, dict) and "doc_id" in metadata:
        return metadata["doc_id"]
    return None


class Metrics:
    """Lexical helpers for retrieval metrics.

    These functions operate on raw text (no embeddings) and are provided as a
    lightweight, dependency-free option. Ground-truth precision is available when
    a set of relevant documents is supplied; otherwise a query-overlap
    approximation is used.
    """

    @staticmethod
    def context_precision(
        query: Optional[str] = None,
        relevant_docs: Optional[Sequence[str]] = None,
        retrieved_docs: Optional[Sequence[Document]] = None,
    ) -> float:
        """Context precision.

        True precision = (relevant ∩ retrieved) / retrieved. When a set of
        ``relevant_docs`` (ground truth) is supplied, the exact formula is used.
        Otherwise precision is approximated by query/retrieved-word overlap, since
        no labelled dataset is available.
        """
        if not retrieved_docs:
            return 0.0

        def _extract_text(doc: Document) -> str:
            return doc.content if hasattr(doc, "content") else str(doc)

        logger = logging.getLogger(__name__)

        if relevant_docs is not None:
            relevant = {str(item) for item in relevant_docs}
            retrieved = {_extract_text(doc) for doc in retrieved_docs}
            if not retrieved:
                return 0.0
            return len(relevant & retrieved) / len(retrieved)

        if query is not None:
            query_words = set(query.lower().split())
            if not query_words:
                return 0.0

            retrieved_words: set = set()
            for doc in retrieved_docs:
                retrieved_words.update(_extract_text(doc).lower().split())

            logger.debug("Query words: %s", query_words)
            logger.debug("Retrieved words: %s", retrieved_words)
            return len(query_words & retrieved_words) / len(query_words)

        raise ValueError("Either relevant_docs or query must be provided")

    @staticmethod
    def context_precision_at_ids(
        relevant_doc_ids: Sequence[Any],
        retrieved_doc_ids: Sequence[Any],
    ) -> float:
        """True precision over document ids: |relevant ∩ retrieved| / |retrieved|."""
        retrieved = set(retrieved_doc_ids)
        if not retrieved:
            return 0.0
        relevant = set(relevant_doc_ids)
        return len(relevant & retrieved) / len(retrieved)

    @staticmethod
    def context_recall_at_ids(
        relevant_doc_ids: Sequence[Any],
        retrieved_doc_ids: Sequence[Any],
    ) -> float:
        """True recall over document ids: |relevant ∩ retrieved| / |relevant|."""
        relevant = set(relevant_doc_ids)
        if not relevant:
            return 0.0
        retrieved = set(retrieved_doc_ids)
        return len(relevant & retrieved) / len(relevant)

    @staticmethod
    def retrieved_doc_ids(retrieved_docs: Optional[Sequence[Document]]) -> list:
        """Extract ``doc_id`` metadata from retrieved documents (order preserved)."""
        ids = []
        for doc in retrieved_docs or []:
            doc_id = _doc_id(doc)
            if doc_id is not None:
                ids.append(doc_id)
        return ids

