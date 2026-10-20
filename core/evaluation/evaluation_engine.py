from typing import Dict, List, Optional, Union

from core.interfaces.embedder import BaseEmbedder
from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.retriever import Document


class EvaluationEngine(BaseEvaluator):
    """Genuine embedding-based evaluation engine.

    Computes real metrics from the request inputs (no hardcoded placeholders):

      * ``context_precision`` - mean cosine similarity between the query and each
        retrieved document.
      * ``answer_relevance``  - cosine similarity between the query and the answer.
      * ``faithfulness``      - mean cosine similarity between the answer and the
        retrieved documents (a proxy for context support).

    The embedding logic is shared with :class:`SemanticEvaluator`; this engine
    simply exposes it under the historical ``engine`` evaluator provider name.
    """

    supports_ground_truth = True

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self._embedder = embedder
        self._model_name = model_name
        self._evaluator: Optional[BaseEvaluator] = None

    def _delegate(self) -> BaseEvaluator:
        if self._evaluator is None:
            from core.implementations.semantic_evaluator import SemanticEvaluator

            self._evaluator = SemanticEvaluator(
                embedder=self._embedder, model_name=self._model_name
            )
        return self._evaluator

    def evaluate(self, query: str, docs: List[Document], response: str) -> Dict[str, float]:
        return self._delegate().evaluate(query=query, retrieved_docs=docs, response=response)

    def evaluate_with_ground_truth(
        self,
        query: str,
        docs: List[Document],
        response: str,
        ground_truth: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, float]:
        return self._delegate().evaluate_with_ground_truth(
            query=query,
            retrieved_docs=docs,
            response=response,
            ground_truth=ground_truth,
        )
