from typing import Dict, List

from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.retriever import Document


class NullEvaluator(BaseEvaluator):
    """
    No-op evaluator used when evaluation is disabled via configuration.
    Returns an empty metrics mapping so the pipeline stays fully functional
    without incurring evaluation cost/latency.
    """

    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str,
    ) -> Dict[str, float]:
        return {}
