from abc import ABC, abstractmethod
from typing import List, Optional
from core.interfaces.retriever import Document, ScoredDocument


class BaseReranker(ABC):
    """
    Contract for document reranking components between retrieval and prompt construction.
    Can be implemented by lexical rerankers, cross-encoders, external reranking APIs, or LLM rerankers.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        """
        Reranks initial candidate documents for the given query and returns reordered Document objects.
        """
        pass

    def rerank_with_scores(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[ScoredDocument]:
        reranked = self.rerank(query=query, documents=documents, top_k=top_k)
        results: List[ScoredDocument] = []
        for idx, doc in enumerate(reranked):
            score = doc.score if getattr(doc, "score", None) is not None else round(max(0.0, 1.0 - idx * 0.1), 4)
            results.append(ScoredDocument(document=doc, score=score))
        return results

    @property
    def reranker_name(self) -> str:
        return self.__class__.__name__
