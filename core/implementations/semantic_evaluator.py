from typing import Dict, List, Optional

import numpy as np

from core.implementations.simple_embedder import SimpleEmbedder
from core.interfaces.embedder import BaseEmbedder
from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.retriever import Document


def _cosine(a: List[float], b: List[float]) -> float:
    vec_a = np.asarray(a, dtype=float)
    vec_b = np.asarray(b, dtype=float)
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


class SemanticEvaluator(BaseEvaluator):
    """
    Genuine evaluator deriving metrics from real embedding-model inference.

    All three metrics are computed from actual sentence embeddings (no hardcoded
    placeholders):
      * context_precision - mean cosine similarity between the query and each
        retrieved document.
      * answer_relevance  - cosine similarity between the query and the answer.
      * faithfulness      - mean cosine similarity between the answer and the
        retrieved documents (a proxy for context support).
    """

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self._embedder = embedder
        self._model_name = model_name

    @property
    def embedder(self) -> BaseEmbedder:
        """Lazily construct the default embedder on first use.

        Building an evaluator is cheap and should not force an expensive model
        load; only evaluating actually needs embeddings.
        """
        if self._embedder is None:
            self._embedder = SimpleEmbedder(self._model_name)
        return self._embedder

    @staticmethod
    def _content(doc: object) -> str:
        return doc.content if hasattr(doc, "content") else str(doc)

    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str,
    ) -> Dict[str, float]:
        query = query or ""
        response = response or ""
        docs = list(retrieved_docs or [])

        embedder = self.embedder
        query_vec = embedder.embed(query)
        answer_vec = embedder.embed(response)

        if docs:
            doc_vecs = [embedder.embed(self._content(doc)) for doc in docs]
            context_precision = sum(_cosine(query_vec, vec) for vec in doc_vecs) / len(doc_vecs)
            faithfulness = sum(_cosine(answer_vec, vec) for vec in doc_vecs) / len(doc_vecs)
        else:
            context_precision = 0.0
            faithfulness = 0.0

        return {
            "context_precision": round(context_precision, 6),
            "answer_relevance": round(_cosine(query_vec, answer_vec), 6),
            "faithfulness": round(faithfulness, 6),
        }
