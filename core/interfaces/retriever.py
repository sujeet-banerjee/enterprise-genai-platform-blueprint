from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any, Optional

class Document:
    """
    Document or Chunk retrieved
    """
    def __init__(self, content: str, metadata: Optional[Dict[str, Any]] = None, score: Optional[float] = None):
        self.content = content
        self.metadata = dict(metadata) if metadata is not None else {}
        self.score = score
        if score is not None and "score" not in self.metadata:
            self.metadata["score"] = score

    def __repr__(self) -> str:
        return f"Document(content={self.content[:30]!r}..., score={self.score})"

class BaseRetriever(ABC):
    """
    Contract for vector retrieval systems.
    """
    @abstractmethod
    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        pass

    def retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[Tuple[Document, float]]:
        """
        Retrieve documents along with their relevance/similarity scores.
        """
        docs = self.retrieve(embedding, top_k=top_k)
        return [(doc, getattr(doc, "score", 0.0) if getattr(doc, "score", None) is not None else 0.0) for doc in docs]

    @property
    @abstractmethod
    def index_dimension(self) -> int:
        """
        Dimension of vectors stored in index.
        """
        pass