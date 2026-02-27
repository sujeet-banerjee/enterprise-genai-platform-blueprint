from abc import ABC, abstractmethod
from typing import List, Dict
from core.interfaces.retriever import Document


class BaseEvaluator(ABC):
    """
    Contract for response evaluation.
    """

    @abstractmethod
    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str
    ) -> Dict[str, float]:
        pass