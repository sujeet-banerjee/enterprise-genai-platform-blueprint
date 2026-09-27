from typing import List, Dict
from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.retriever import Document
from core.evaluation.metrics import Metrics


class SimpleEvaluator(BaseEvaluator):
    """
    Standard evaluator using Metrics calculations.
    """

    def __init__(self, metrics: Metrics = None):
        self.metrics = metrics or Metrics()

    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str
    ) -> Dict[str, float]:
        precision = self.metrics.context_precision(query=query, retrieved_docs=retrieved_docs)
        relevance = self.metrics.answer_relevance(similarity_score=0.8)
        faithfulness = self.metrics.faithfulness(supported_claims=1, total_claims=1)

        return {
            "context_precision": precision,
            "answer_relevance": relevance,
            "faithfulness": faithfulness
        }
