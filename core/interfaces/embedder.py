from abc import ABC, abstractmethod
from typing import List


class BaseEmbedder(ABC):
    """
    Contract for all embedding providers.
    """

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """
        Returns embedding vector for given text.
        """
        pass

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Returns embedding vectors for multiple texts (issue #27).

        Providers that can encode several inputs in one call (local
        Sentence-Transformers, OpenAI) override this for real batching. The
        default keeps the single-item path alive by embedding one at a time, so
        implementations remain interchangeable: ``embed_batch`` output is always
        equivalent to ``[self.embed(t) for t in texts]``.
        """
        return [self.embed(text) for text in texts]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """
        Returns embedding vector dimension.
        """
        pass

    @property
    def model_name(self) -> str:
        """
        Returns identifier of the underlying embedding model.
        """
        return getattr(self, "_model_name", self.__class__.__name__)
