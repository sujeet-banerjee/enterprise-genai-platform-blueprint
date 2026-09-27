import re
from typing import List, Tuple, Optional
from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document


class SimpleReranker(BaseReranker):
    """
    Basic/lexical reranker suitable for local experimentation.
    Combines initial retrieval scores with query term overlap and exact phrase matching.
    """

    def __init__(self, initial_weight: float = 0.5, lexical_weight: float = 0.5):
        self.initial_weight = initial_weight
        self.lexical_weight = lexical_weight

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\w+", text.lower())

    def _compute_lexical_score(self, query: str, doc_text: str) -> float:
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return 0.0

        d_tokens = set(self._tokenize(doc_text))
        overlap = sum(1 for token in q_tokens if token in d_tokens)
        overlap_score = overlap / len(q_tokens)

        # Exact phrase match boost
        phrase_boost = 0.2 if query.strip().lower() in doc_text.lower() else 0.0

        return min(1.0, overlap_score + phrase_boost)

    def rerank(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[Document]:
        if not documents:
            return []

        scored_docs: List[Tuple[Document, float]] = []

        for doc in documents:
            initial_score = doc.score if doc.score is not None else 0.5
            lexical_score = self._compute_lexical_score(query, doc.content)

            combined_score = (self.initial_weight * initial_score) + (self.lexical_weight * lexical_score)

            # Create a shallow/annotated copy with updated score
            new_metadata = dict(doc.metadata) if doc.metadata else {}
            new_metadata["initial_score"] = initial_score
            new_metadata["rerank_score"] = combined_score

            reranked_doc = Document(
                content=doc.content,
                metadata=new_metadata,
                score=round(combined_score, 4)
            )
            scored_docs.append((reranked_doc, combined_score))

        # Sort by combined score descending
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        results = [doc for doc, _ in scored_docs]
        if top_k is not None and top_k > 0:
            results = results[:top_k]
        return results


class NoOpReranker(BaseReranker):
    """
    Pass-through reranker that maintains the initial retrieval ordering.
    """

    def rerank(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[Document]:
        if top_k is not None and top_k > 0:
            return documents[:top_k]
        return documents
