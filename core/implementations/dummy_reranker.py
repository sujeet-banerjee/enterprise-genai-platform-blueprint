from typing import List, Optional
from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document


class DummyReranker(BaseReranker):
    """
    Lightweight dummy reranker for testing and baseline comparisons.
    """

    def __init__(self, reverse: bool = False):
        self.reverse = reverse

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        docs = list(reversed(documents)) if self.reverse else list(documents)
        if top_k is not None:
            docs = docs[:top_k]
        return docs
