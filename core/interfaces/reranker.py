from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from core.interfaces.retriever import Document


class BaseReranker(ABC):
    """
    Contract for document reranking components.
    """

    @abstractmethod
    def rerank(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[Document]:
        """
        Reranks a list of candidate documents based on query relevance.
        """
        pass

    def rerank_with_scores(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[Tuple[Document, float]]:
        """
        Reranks documents and returns a list of (Document, score) tuples.
        """
        reranked = self.rerank(query, documents, top_k=top_k)
        return [(doc, getattr(doc, "score", 0.0) if getattr(doc, "score", None) is not None else 0.0) for doc in reranked]
