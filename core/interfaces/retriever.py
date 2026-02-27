from abc import ABC, abstractmethod
from typing import List

class Document:
    """
    Document or Chunk retrieved
    """
    def __init__(self, content: str, metadata:dict=None):
        self.content = content
        self.metadata = metadata

class BaseRetriever(ABC):
    """
    Contract for vector retrieval systems.
    """
    @abstractmethod
    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        pass

    @property
    @abstractmethod
    def index_dimension(self) -> int:
        """
        Dimension of vectors stored in index.
        """
        pass