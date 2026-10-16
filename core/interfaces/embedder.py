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
