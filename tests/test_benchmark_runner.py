"""Tests for issue #22: labelled benchmark dataset + true IR metrics + runner.

Covers:
* the in-repo benchmark file loads and validates;
* true context precision / recall over document ids;
* ``BenchmarkRunner`` end-to-end (deterministic injected retriever for speed, and
  one real-embedder integration run over the benchmark corpus).
"""

from pathlib import Path

import pytest

from core.evaluation.benchmark_runner import BenchmarkRunner, load_benchmark
from core.evaluation.metrics import Metrics
from core.interfaces.retriever import BaseRetriever, Document

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_ROOT / "data" / "benchmark.json"


# -- dataset ---------------------------------------------------------------


def test_benchmark_file_ships_with_documented_schema():
    data = load_benchmark(str(BENCHMARK_PATH))
    assert data["docs"], "benchmark must ship documents"
    assert data["cases"], "benchmark must ship labelled cases"
    for case in data["cases"]:
        assert isinstance(case["query"], str) and case["query"]
        assert isinstance(case["relevant_doc_ids"], list)
        for doc_id in case["relevant_doc_ids"]:
            assert 0 <= doc_id < len(data["docs"])


def test_load_benchmark_rejects_bad_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"docs": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_benchmark(str(bad))


# -- true IR metrics -------------------------------------------------------


def test_context_precision_at_ids():
    assert Metrics.context_precision_at_ids([0, 1], [0, 2, 3]) == pytest.approx(1 / 3)
    assert Metrics.context_precision_at_ids([0], []) == 0.0


def test_context_recall_at_ids():
    assert Metrics.context_recall_at_ids([0, 1], [0, 5]) == pytest.approx(0.5)
    assert Metrics.context_recall_at_ids([], [1, 2]) == 0.0


def test_retrieved_doc_ids_reads_metadata():
    docs = [
        Document(content="a", metadata={"doc_id": 3}),
        Document(content="b", metadata={"doc_id": 1}),
        Document(content="c"),
    ]
    assert Metrics.retrieved_doc_ids(docs) == [3, 1]


# -- runner (deterministic injected retriever) -----------------------------


class _KeywordRetriever(BaseRetriever):
    """Deterministic retriever: returns docs whose content shares query words."""

    def __init__(self, docs, embedder=None):
        self.docs = [
            Document(content=str(d["content"]), metadata={"doc_id": idx})
            for idx, d in enumerate(docs)
        ]

    @property
    def index_dimension(self) -> int:
        return 8

    def retrieve(self, embedding, top_k=3):
        return self.docs[:top_k]


class _FixedEmbedder:
    dimension = 8

    def embed(self, text):
        return [0.0] * self.dimension


def test_runner_reports_true_metrics_with_injected_retriever():
    runner = BenchmarkRunner(
        benchmark_path=str(BENCHMARK_PATH),
        retriever=_KeywordRetriever(load_benchmark(str(BENCHMARK_PATH))["docs"]),
        embedder=_FixedEmbedder(),
    )
    report = runner.run(top_k=4)

    assert report["num_cases"] == len(load_benchmark(str(BENCHMARK_PATH))["cases"])
    assert report["top_k"] == 4
    assert 0.0 <= report["context_precision"] <= 1.0
    assert 0.0 <= report["context_recall"] <= 1.0
    assert len(report["cases"]) == report["num_cases"]
    for case in report["cases"]:
        assert {"query", "relevant_doc_ids", "retrieved_doc_ids"} <= set(case)


def test_runner_perfect_retriever_scores_one():
    data = load_benchmark(str(BENCHMARK_PATH))

    class _QueryCarryingEmbedder:
        """Records the last query so a stub retriever can return its perfect set."""

        dimension = 8

        def __init__(self):
            self.last_query = None

        def embed(self, text):
            self.last_query = text
            return [0.0] * self.dimension

    embedder = _QueryCarryingEmbedder()
    by_query = {
        case["query"]: [
            Document(
                content=str(data["docs"][doc_id]["content"]),
                metadata={"doc_id": doc_id},
            )
            for doc_id in case["relevant_doc_ids"]
        ]
        for case in data["cases"]
    }

    class _PerfectRetriever(BaseRetriever):
        @property
        def index_dimension(self) -> int:
            return 8

        def retrieve(self, embedding, top_k=3):
            return by_query.get(embedder.last_query, [])

    runner = BenchmarkRunner(
        benchmark_path=str(BENCHMARK_PATH),
        retriever=_PerfectRetriever(),
        embedder=embedder,
    )
    report = runner.run(top_k=3)
    assert report["context_precision"] == 1.0
    assert report["context_recall"] == 1.0


# -- runner integration with the real embedder + SimpleRetriever -----------


def test_runner_integration_with_real_retriever(real_embedder):
    data = load_benchmark(str(BENCHMARK_PATH))
    from core.implementations.simple_retriever import SimpleRetriever

    retriever = SimpleRetriever(docs=data["docs"], embedder=real_embedder)
    runner = BenchmarkRunner(
        benchmark_path=str(BENCHMARK_PATH),
        retriever=retriever,
        embedder=real_embedder,
    )
    report = runner.run(top_k=3)

    assert report["num_cases"] == len(data["cases"])
    # A real embedding retriever should recover a good share of relevant docs.
    assert report["context_recall"] > 0.0
    assert 0.0 <= report["context_precision"] <= 1.0
