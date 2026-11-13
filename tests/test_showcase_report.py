"""Tests for the reproducible showcase benchmark report (issue #196)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app import benchmark_report
from core.evaluation.benchmarks import load_benchmarks_config, resolve_suite
from core.evaluation.eval_datasets import EvalCase, EvalDataset
from core.evaluation.metrics import Metrics
from core.evaluation.showcase_report import (
    REPORT_SCHEMA_VERSION,
    ShowcaseReportError,
    check_report,
    load_report,
    render_csv,
    render_markdown,
    run_suite_report,
)


class FakeRunner:
    """Deterministic stand-in for ExperimentRunner (no models, no network)."""

    def __init__(self) -> None:
        self.calls = 0

    def run_single_experiment(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        top_k = int(kwargs.get("top_k") or 3)
        doc_ids = list(range(top_k)) if top_k <= 3 else list(range(1, top_k + 1))
        return {
            "retrieved_docs_with_scores": [
                {"content": f"doc {doc_id}", "metadata": {"doc_id": doc_id}}
                for doc_id in doc_ids
            ],
            "metrics": {"answer_relevance": 0.5},
            "cost_usd": 0.001 * top_k,
            "latency_summary": {"total_ms": 10.0 * top_k},
        }


def _dataset(name: str, *, num_cases: int = 2) -> EvalDataset:
    docs = [{"content": f"{name} doc 0"}, {"content": f"{name} doc 1"}]
    case = EvalCase(query=f"{name} query", relevant_doc_ids=(0,))
    return EvalDataset(
        name=name,
        path="benchmarks/data/support/benchmark.json",
        format="json",
        cases=[case] * num_cases,
        docs=docs,
        metadata={"domain": name},
    )


def _custom_suite() -> dict:
    return {
        "name": "test-suite",
        "description": "test",
        "datasets": ["one", "two"],
        "max_cases": 0,
        "max_combinations": 4,
        "parameters": {"top_k": [3, 5], "reranker": [False]},
        "objective": {"quality": "context_recall", "cost_budget_usd": 0.01},
    }


def test_mrr_at_ids_ranks_first_relevant_hit() -> None:
    assert Metrics.mrr_at_ids([2], [0, 1, 2]) == pytest.approx(1 / 3)
    assert Metrics.mrr_at_ids([0], [0, 1]) == 1.0
    assert Metrics.mrr_at_ids([9], [0, 1]) == 0.0
    assert Metrics.mrr_at_ids([], [0, 1]) == 0.0


def test_ndcg_at_ids_rewards_early_hits_and_honours_k() -> None:
    assert Metrics.ndcg_at_ids([0, 1], [0, 1]) == pytest.approx(1.0)
    assert Metrics.ndcg_at_ids([0], [0, 1]) == pytest.approx(1.0)
    assert Metrics.ndcg_at_ids([9], [0, 1]) == 0.0
    assert Metrics.ndcg_at_ids([], [0, 1]) == 0.0
    assert Metrics.ndcg_at_ids([1], [0, 1], k=1) == 0.0
    assert Metrics.ndcg_at_ids([1], [0, 1]) == pytest.approx(1 / 1.584962500721156)


def test_run_suite_report_has_provenance_and_metrics() -> None:
    config = load_benchmarks_config()
    suite = resolve_suite(config, "quick")
    from core.evaluation.benchmarks import load_suite_datasets

    datasets = load_suite_datasets(config, suite)
    report = run_suite_report(
        suite,
        datasets,
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["num_combinations"] == 1
    assert report["datasets"][0]["name"] == "support"
    assert report["datasets"][0]["sha256"]
    assert report["provenance"]["git_sha"] not in ("", "unknown")
    assert report["provenance"]["config_sha256"]
    assert report["provenance"]["seed"] == 0
    row = report["rows"][0]
    assert "mrr" in row["metrics"] and "ndcg" in row["metrics"]
    assert row["metrics"]["mrr"] >= 0.0
    assert row["metrics"]["ndcg"] >= 0.0
    assert row["quality_metric"] == "context_recall"
    assert report["recommended"]["combination_id"] == row["combination_id"]


def test_run_suite_report_aggregates_datasets_and_pareto() -> None:
    datasets = [_dataset("one"), _dataset("two")]
    report = run_suite_report(
        _custom_suite(),
        datasets,
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )

    assert report["num_combinations"] == 2
    assert len(report["rows"]) == 2
    by_top_k = {row["parameters"]["top_k"]: row for row in report["rows"]}
    assert by_top_k[3]["metrics"]["context_recall"] == pytest.approx(1.0)
    assert by_top_k[5]["metrics"]["context_recall"] == pytest.approx(0.0)
    assert by_top_k[3]["num_cases"] == 4
    assert by_top_k[3]["cost_usd"] == pytest.approx(0.003)
    assert report["pareto_frontier"] == [by_top_k[3]["combination_id"]]
    assert report["recommended"]["parameters"]["top_k"] == 3


def test_markdown_and_csv_are_rendered_from_the_report() -> None:
    report = run_suite_report(
        _custom_suite(),
        [_dataset("one"), _dataset("two")],
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )

    markdown = render_markdown(report)
    assert "Showcase benchmark report" in markdown
    assert report["provenance"]["git_sha"] in markdown
    assert report["provenance"]["config_sha256"] in markdown
    assert "one" in markdown and "two" in markdown
    for row in report["rows"]:
        assert row["combination_id"] in markdown

    rows = list(csv.DictReader(io.StringIO(render_csv(report))))
    assert len(rows) == report["num_combinations"]
    assert rows[0]["quality_metric"] == "context_recall"
    assert {row["combination_id"] for row in rows} == {
        row["combination_id"] for row in report["rows"]
    }


def test_check_report_passes_generated_report() -> None:
    report = run_suite_report(
        _custom_suite(),
        [_dataset("one")],
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )
    assert check_report(report) == []


def test_check_report_rejects_missing_provenance_datasets_and_rows() -> None:
    report = run_suite_report(
        _custom_suite(),
        [_dataset("one")],
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )
    report["provenance"].pop("git_sha")
    report["datasets"] = []
    report["rows"] = []
    problems = check_report(report)
    assert any("provenance.git_sha" in problem for problem in problems)
    assert any("datasets" in problem for problem in problems)
    assert any("rows" in problem for problem in problems)


def test_build_report_rejects_suites_without_datasets_or_parameters() -> None:
    with pytest.raises(ShowcaseReportError):
        run_suite_report(_custom_suite(), [], runner=FakeRunner())
    suite = _custom_suite()
    suite["parameters"] = {}
    with pytest.raises(ShowcaseReportError):
        run_suite_report(suite, [_dataset("one")], runner=FakeRunner())


def test_cli_quick_check_end_to_end_with_smoke_config(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    csv_path = tmp_path / "report.csv"

    code = benchmark_report.main(
        [
            "--quick",
            "--config-dir",
            "deployment/smoke/config",
            "--out",
            str(out),
            "--markdown",
            str(markdown),
            "--csv",
            str(csv_path),
            "--check",
        ]
    )

    assert code == 0
    assert out.exists() and markdown.exists() and csv_path.exists()
    report = load_report(out)
    assert report["suite"]["suite"] == "quick"
    assert check_report(report) == []
    assert "Showcase benchmark report" in markdown.read_text(encoding="utf-8")


def test_cli_check_fails_on_tampered_existing_report(tmp_path: Path) -> None:
    report = run_suite_report(
        _custom_suite(),
        [_dataset("one")],
        runner=FakeRunner(),
        config_path="config/benchmarks.yaml",
    )
    report["provenance"].pop("config_sha256")
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(report), encoding="utf-8")

    assert benchmark_report.main(["--check", "--out", str(target)]) == 1


def test_cli_unknown_suite_exits_two(tmp_path: Path) -> None:
    assert (
        benchmark_report.main(
            ["--suite", "does-not-exist", "--out", str(tmp_path / "x.json")]
        )
        == 2
    )


def test_cli_rejects_oversized_sweep(tmp_path: Path) -> None:
    assert (
        benchmark_report.main(
            [
                "--suite",
                "showcase",
                "--max-combinations",
                "1",
                "--out",
                str(tmp_path / "x.json"),
            ]
        )
        == 2
    )
