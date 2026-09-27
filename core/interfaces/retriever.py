from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class Document:
    """
    Document or Chunk retrieved
    """
    def __init__(self, content: str, metadata: dict = None, score: Optional[float] = None):
        self.content = content
        self.metadata = dict(metadata) if metadata is not None else {}
        if score is not None:
            self.score = float(score)
            self.metadata["score"] = float(score)
        elif "score" in self.metadata and self.metadata["score"] is not None:
            self.score = float(self.metadata["score"])
        else:
            self.score = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
        }


class ScoredDocument(Document):
    """
    Structured representation of a retrieved document with its similarity/relevance score.
    Supports attribute access (.content, .score, .metadata, .document),
    tuple unpacking (doc, score), and key indexing.
    """
    def __init__(
        self,
        content: str = "",
        metadata: dict = None,
        score: float = 0.0,
        document: Optional[Document] = None,
    ):
        if document is not None:
            merged_meta = dict(document.metadata) if document.metadata else {}
            if metadata:
                merged_meta.update(metadata)
            super().__init__(content=document.content, metadata=merged_meta, score=score)
            self._document = document
            self._document.score = float(score)
            if self._document.metadata is None:
                self._document.metadata = {}
            self._document.metadata["score"] = float(score)
        else:
            super().__init__(content=content, metadata=metadata, score=score)
            self._document = self

    @property
    def document(self) -> Document:
        return self._document

    def __iter__(self):
        yield self._document
        yield self.score

    def __getitem__(self, key):
        if key == 0 or key == "document":
            return self._document
        if key == 1 or key == "score":
            return self.score
        if key == "content":
            return self.content
        if key == "metadata":
            return self.metadata
        raise KeyError(key)


class BaseRetriever(ABC):
    """
    Contract for vector retrieval systems.
    """
    @abstractmethod
    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        pass

    def retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        docs = self.retrieve(embedding, top_k=top_k)
        scored: List[ScoredDocument] = []
        for idx, doc in enumerate(docs):
            score = doc.score if getattr(doc, "score", None) is not None else round(max(0.0, 1.0 - idx * 0.1), 4)
            scored.append(ScoredDocument(document=doc, score=score))
        return scored

    @property
    @abstractmethod
    def index_dimension(self) -> int:
        """
        Dimension of vectors stored in index.
        """
        pass
