from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

from core.interfaces.retriever import Document


def normalize_references(
    ground_truth: Optional[Union[str, List[str]]],
) -> List[str]:
    """Coerce the ground-truth argument into a list of non-empty references."""
    if ground_truth is None:
        return []
    if isinstance(ground_truth, str):
        candidates: List[str] = [ground_truth]
    else:
        candidates = list(ground_truth)
    return [
        reference
        for reference in candidates
        if isinstance(reference, str) and reference.strip()
    ]


class BaseEvaluator(ABC):
    """
    Contract for response evaluation.
    """

    #: Whether this evaluator genuinely consumes a ground-truth reference.
    #: Overridden to ``True`` by evaluators that implement
    #: :meth:`evaluate_with_ground_truth` with real ground-truth-aware metrics;
    #: the API uses this flag to report ``ground_truth_used`` honestly.
    supports_ground_truth: bool = False

    @abstractmethod
    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str
    ) -> Dict[str, float]:
        pass

    def evaluate_with_ground_truth(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str,
        ground_truth: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, float]:
        """Ground-truth-aware evaluation.

        Optional capability: the default implementation ignores ``ground_truth``
        and delegates to :meth:`evaluate`, so evaluators that cannot use a
        reference answer still work unchanged. Evaluators that support it (e.g.
        ``SemanticEvaluator``, ``LLMJudgeEvaluator``) override this, set
        :attr:`supports_ground_truth` to ``True`` and return a genuine,
        ground-truth-aware ``answer_correctness`` in addition to their regular
        metrics.
        """
        return self.evaluate(query=query, retrieved_docs=retrieved_docs, response=response)
