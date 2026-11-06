"""UX3 follow-up (#145): dataset evaluation workflow tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ui import evaluation

REPO_BASE = Path(__file__).resolve().parents[1]


def _case(query: str = "What is RAG?", reference: str = "RAG grounds answers.") -> evaluation.EvaluationCase:
    return evaluation.EvaluationCase(query=query, reference=reference, tags=("rag",))


class _FakeResult:
    def __init__(self, ok: bool, data: dict | None = None, status_code: int = 200, error: str | None = None):
        self.ok = ok
        self.data = data or {}
        self.status_code = status_code
        self.error = error


class _FakeApi:
    def __init__(self) -> None:
        self.query_calls: list[dict] = []
        self.evaluate_calls: list[dict] = []

    def query(self, query: str, top_k: int | None = None, include_trace: bool = True):
        self.query_calls.append({"query": query, "top_k": top_k, "include_trace": include_trace})
        if "query failure" in query:
            return _FakeResult(False, {"error": "query failed upstream"}, status_code=400)
        return _FakeResult(
            True,
            {
                "response": f"answer for {query}",
                "retrieved_docs": [{"content": "doc-a"}, {"content": "doc-b"}],
            },
        )

    def evaluate(
        self,
        query: str,
        response: str,
        retrieved_docs=None,
        ground_truth=None,
        evaluator=None,
        top_k=None,
    ):
        self.evaluate_calls.append(
            {
                "query": query,
                "response": response,
                "retrieved_docs": retrieved_docs,
                "ground_truth": ground_truth,
                "evaluator": evaluator,
                "top_k": top_k,
            }
        )
        if "eval failure" in query:
            return _FakeResult(False, {"error": "evaluation failed upstream"}, status_code=500)
        return _FakeResult(
            True,
            {
                "evaluator": evaluator or "semantic",
                "metrics": {
                    "context_precision": 0.5,
                    "answer_relevance": 0.9,
                    "faithfulness": 0.4 if "weak" in query else 0.8,
                },
                "ground_truth_used": bool(ground_truth),
                "docs_source": "provided" if retrieved_docs else "auto",
                "num_retrieved_docs": len(retrieved_docs or []),
                "request_id": f"req-{len(self.evaluate_calls)}",
            },
        )


def test_parse_benchmark_cases_turns_relevant_ids_into_references():
    cases = evaluation.parse_dataset_json(
        """
        {
          "docs": [
            {"content": "Artificial Intelligence is the simulation of human intelligence."},
            {"content": "Machine Learning is a subset of AI."}
          ],
          "cases": [{"query": "What is AI?", "relevant_doc_ids": [0, 1, 99]}]
        }
        """
    )
    assert len(cases) == 1
    assert cases[0].query == "What is AI?"
    assert "simulation of human intelligence" in cases[0].reference
    assert "subset of AI" in cases[0].reference


def test_parse_accepts_reference_aliases_and_string_tags():
    cases = evaluation.parse_dataset_json(
        """
        [{"question": "What is ML?", "reference": ["learning from data", "a subset of AI"],
          "tags": "definition"}]
        """
    )
    assert cases[0].query == "What is ML?"
    assert cases[0].reference == "learning from data a subset of AI"
    assert cases[0].tags == ("definition",)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not-json", "Invalid JSON"),
        ("{}", "at least one case"),
        ('{"cases": []}', "at least one case"),
        ('[{"reference": "no query"}]', "missing a `query`"),
        ('["not an object"]', "must be a JSON object"),
    ],
)
def test_parse_rejects_malformed_datasets(payload: str, message: str):
    with pytest.raises(ValueError, match=message):
        evaluation.parse_dataset_json(payload)


def test_load_benchmark_cases_reads_the_shipped_dataset():
    cases = evaluation.load_benchmark_cases(str(REPO_BASE / "data" / "benchmark.json"))
    assert len(cases) == 6
    assert cases[0].query == "What is artificial intelligence?"
    assert "simulation of human intelligence" in cases[0].reference
    assert all(case.reference for case in cases)


def test_build_row_and_metric_matrix_keep_identity_but_drop_metadata():
    cases = [_case("q1"), _case("q2")]
    rows = [
        evaluation.build_evaluation_row(cases[0], {"metrics": {"faithfulness": 0.8}}, index=1),
        evaluation.build_evaluation_row(cases[1], index=2, error="boom"),
    ]
    assert rows[0]["case"] == 1
    assert rows[1]["status"] == "error"
    matrix = evaluation.metric_matrix(rows)
    assert [row["case"] for row in matrix] == [1, 2]
    assert [row["query"] for row in matrix] == ["q1", "q2"]
    assert matrix[0]["faithfulness"] == 0.8
    assert matrix[1]["faithfulness"] is None
    assert "request_id" not in matrix[0]
    assert "error" not in matrix[0]


def test_metric_summary_averages_finite_numbers_only():
    rows = [
        {"faithfulness": 0.5, "answer_relevance": 1.0, "flag": True},
        {"faithfulness": 1.0, "answer_relevance": float("nan")},
        {"faithfulness": None, "answer_relevance": 0.4},
    ]
    summary = evaluation.metric_summary(rows, ["faithfulness", "answer_relevance", "flag"])
    assert summary["faithfulness"] == 0.75
    assert summary["answer_relevance"] == 0.7
    assert "flag" not in summary


def test_compare_metric_averages_reports_direction_and_missing_metrics():
    previous = [{"context_precision": 0.4, "faithfulness": 0.8}]
    current = [{"context_precision": 0.4, "faithfulness": 0.5, "answer_relevance": 0.9}]
    rows = {row["metric"]: row for row in evaluation.compare_metric_averages(previous, current)}
    assert rows["Context precision"]["delta"] == 0
    assert rows["Context precision"]["direction"] == "unchanged"
    assert rows["Faithfulness"]["delta"] == -0.3
    assert rows["Faithfulness"]["direction"] == "down"
    assert rows["Answer relevance"]["previous"] is None
    assert rows["Answer relevance"]["direction"] == "-"


def test_preview_and_case_limit_are_bounded():
    cases = [_case(f"q{index}") for index in range(1, 25)]
    preview = evaluation.dataset_preview_rows(cases[:2])
    assert preview[0]["#"] == 1
    assert preview[0]["tags"] == "rag"
    assert evaluation.limit_cases(cases, 2) == cases[:2]
    assert evaluation.limit_cases(cases, 0) == []
    assert len(evaluation.limit_cases(cases, 999)) == evaluation.MAX_DATASET_CASES


def test_run_dataset_evaluation_passes_query_answer_docs_and_reference():
    api = _FakeApi()
    cases = [_case("What is RAG?", "RAG grounds answers."), _case("What is ML?", "ML learns.")]
    rows = evaluation.run_dataset_evaluation(
        cases, api, evaluator="(active)", top_k=4
    )
    assert [row["status"] for row in rows] == ["ok", "ok"]
    assert [row["ground_truth_used"] for row in rows] == [True, True]
    assert len(api.query_calls) == 2
    assert all(call["include_trace"] is False for call in api.query_calls)
    assert all(call["top_k"] == 4 for call in api.query_calls)
    first_eval = api.evaluate_calls[0]
    assert first_eval["response"] == "answer for What is RAG?"
    assert first_eval["retrieved_docs"] == [{"content": "doc-a"}, {"content": "doc-b"}]
    assert first_eval["ground_truth"] == "RAG grounds answers."
    assert first_eval["evaluator"] is None


def test_run_dataset_evaluation_isolates_failures_and_reports_progress():
    api = _FakeApi()
    cases = [
        _case("good"),
        _case("query failure"),
        _case("eval failure"),
        _case("weak but good"),
    ]
    progress: list[tuple[int, int]] = []
    rows = evaluation.run_dataset_evaluation(
        cases,
        api,
        evaluator="semantic",
        top_k=2,
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert [row["status"] for row in rows] == ["ok", "error", "error", "ok"]
    assert "query failed upstream" in rows[1]["error"]
    assert "evaluation failed upstream" in rows[2]["error"]
    assert len(api.query_calls) == 4
    assert len(api.evaluate_calls) == 3
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert rows[-1]["faithfulness"] == 0.4
    assert api.evaluate_calls[0]["evaluator"] == "semantic"


def test_run_dataset_evaluation_limits_cases():
    api = _FakeApi()
    cases = [_case(f"q{index}") for index in range(5)]
    rows = evaluation.run_dataset_evaluation(cases, api, max_cases=2)
    assert len(rows) == 2
    assert len(api.query_calls) == 2


def test_evaluation_screen_wires_dataset_workflow():
    src = (REPO_BASE / "ui" / "app.py").read_text(encoding="utf-8")
    for token in (
        "Dataset evaluation",
        "load_benchmark_cases",
        "parse_dataset_json",
        "run_dataset_evaluation",
        "metric_matrix",
        "metric_summary",
        "compare_metric_averages",
        "Failed cases",
    ):
        assert token in src


def test_evaluation_helper_module_stays_pure():
    source = (REPO_BASE / "ui" / "evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for module in imported:
        assert module != "streamlit"
        assert not module.startswith("app")
        assert not module.startswith("core")
