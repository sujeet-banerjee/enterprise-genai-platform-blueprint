"""Ground-truth benchmark runner (issue #22).

Loads a labelled benchmark (query -> relevant document ids) and reports *true* IR
metrics (context precision and recall) by running retrieval for each query and
comparing the retrieved document ids against the labelled relevance judgements.

The runner is configuration-driven by default (it builds a retriever through
``RetrieverRegistry``), but a retriever/embedder can be injected for tests or for
programmatic use.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.evaluation.metrics import Metrics
from core.interfaces.retriever import BaseRetriever, Document

DEFAULT_BENCHMARK_PATH = "data/benchmark.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_benchmark(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and validate a benchmark file, returning its parsed contents."""
    target = Path(path) if path else _repo_root() / DEFAULT_BENCHMARK_PATH
    if not target.is_absolute():
        target = _repo_root() / target
    with open(target, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or "docs" not in data or "cases" not in data:
        raise ValueError(
            f"Benchmark file '{target}' must be an object with 'docs' and 'cases'."
        )
    if not isinstance(data["docs"], list) or not isinstance(data["cases"], list):
        raise ValueError(f"Benchmark file '{target}' needs list 'docs' and 'cases'.")
    for case in data["cases"]:
        if "query" not in case or "relevant_doc_ids" not in case:
            raise ValueError("Each benchmark case needs 'query' and 'relevant_doc_ids'.")
    return data


class BenchmarkRunner:
    """Runs a labelled benchmark and reports true IR metrics."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        *,
        benchmark_path: Optional[str] = None,
        retriever: Optional[BaseRetriever] = None,
        embedder: Any = None,
        retriever_name: Optional[str] = None,
    ):
        self.config_path = config_path
        self.benchmark_path = benchmark_path
        self._retriever = retriever
        self._embedder = embedder
        self.retriever_name = retriever_name

    # -- internals --------------------------------------------------------

    def _load_embedder(self) -> Any:
        if self._embedder is None:
            from core.registry.model_registry import ModelRegistry

            self._embedder = ModelRegistry(self.config_path).get_embedder()
        return self._embedder

    def _build_retriever(self, docs: Sequence[Any]) -> BaseRetriever:
        if self._retriever is not None:
            return self._retriever
        from core.registry.retriever_registry import RetrieverRegistry

        registry = RetrieverRegistry(self.config_path)
        return registry.create(
            name=self.retriever_name,
            docs=docs,
            embedder=self._load_embedder(),
            chunk=False,
        )

    @staticmethod
    def _retrieve(retriever: BaseRetriever, embedding: List[float], top_k: int) -> List[Document]:
        try:
            return list(retriever.retrieve(embedding, top_k=top_k) or [])
        except TypeError:
            return list(retriever.retrieve(embedding) or [])

    # -- public API -------------------------------------------------------

    def run(self, top_k: int = 3) -> Dict[str, Any]:
        data = load_benchmark(self.benchmark_path)
        docs = data["docs"]
        cases = data["cases"]

        retriever = self._build_retriever(docs)
        embedder = self._load_embedder()

        case_results: List[Dict[str, Any]] = []
        precisions: List[float] = []
        recalls: List[float] = []

        for case in cases:
            query = str(case["query"])
            relevant_ids = list(case["relevant_doc_ids"])
            embedding = embedder.embed(query)
            retrieved = self._retrieve(retriever, embedding, top_k)
            retrieved_ids = Metrics.retrieved_doc_ids(retrieved)

            precision = Metrics.context_precision_at_ids(relevant_ids, retrieved_ids)
            recall = Metrics.context_recall_at_ids(relevant_ids, retrieved_ids)
            precisions.append(precision)
            recalls.append(recall)

            case_results.append(
                {
                    "query": query,
                    "relevant_doc_ids": relevant_ids,
                    "retrieved_doc_ids": retrieved_ids,
                    "context_precision": round(precision, 6),
                    "context_recall": round(recall, 6),
                }
            )

        count = len(cases) or 1
        return {
            "num_cases": len(cases),
            "top_k": top_k,
            "context_precision": round(sum(precisions) / count, 6),
            "context_recall": round(sum(recalls) / count, 6),
            "cases": case_results,
        }
