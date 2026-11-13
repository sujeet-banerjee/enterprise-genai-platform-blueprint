"""Tests for published benchmark result integrity, indexing and plots (issue #198)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from app import benchmark_results as benchmark_results_cli
from core.evaluation.benchmark_plots import (
    render_latency_svg,
    render_pareto_svg,
    write_plots,
)
from core.evaluation.benchmark_results import (
    discover_results,
    index_problems,
    render_results_index,
    validate_result,
)
from core.evaluation.benchmarks import load_benchmarks_config, resolve_suite
from core.evaluation.config_sweep import expand_combinations, normalize_parameters
from core.evaluation.eval_datasets import EvalCase, EvalDataset
from core.evaluation.showcase_report import run_suite_report, write_report

SUPPORT_DATA = "benchmarks/data/support/benchmark.json"


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run_single_experiment(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        top_k = int(kwargs.get("top_k") or 3)
        return {
            "retrieved_docs_with_scores": [
                {"content": f"doc {doc_id}", "metadata": {"doc_id": doc_id}}
                for doc_id in range(top_k)
            ],
            "metrics": {"answer_relevance": 0.5},
            "cost_usd": 0.001 * top_k,
            "latency_summary": {"total_ms": 10.0 * top_k},
        }


def _dataset(name: str, *, num_cases: int = 2) -> EvalDataset:
    case = EvalCase(query=f"{name} query", relevant_doc_ids=(0,))
    return EvalDataset(
        name=name,
        path=SUPPORT_DATA,
        format="json",
        cases=[case] * num_cases,
        docs=[{"content": f"{name} doc 0"}, {"content": f"{name} doc 1"}],
        metadata={"domain": name},
    )


def _suite(name: str = "unit") -> dict:
    return {
        "name": name,
        "description": "unit",
        "datasets": ["one", "two"],
        "max_cases": 0,
        "max_combinations": 4,
        "parameters": {"top_k": [3, 5], "reranker": [False]},
        "objective": {"quality": "context_recall", "cost_budget_usd": 0.01},
    }


def _report() -> dict:
    return run_suite_report(_suite(), [_dataset("one"), _dataset("two")], runner=FakeRunner())


def _expected_stem(report: Mapping[str, Any]) -> str:
    provenance = report["provenance"]
    return f"{provenance['timestamp'][:10]}-{provenance['git_sha'][:7]}"


def _write_bundle(directory: Path, report: Mapping[str, Any], stem: str | None = None) -> str:
    name = stem or _expected_stem(report)
    write_report(
        report,
        out=directory / f"{name}.json",
        markdown=directory / f"{name}.md",
        csv_path=directory / f"{name}.csv",
    )
    write_plots(report, directory, stem=name)
    return name


def test_provenance_embeds_a_verifiable_config_snapshot() -> None:
    report = _report()
    provenance = report["provenance"]
    snapshot = provenance["config_snapshot"]
    assert snapshot.strip()
    assert "reference" in snapshot
    assert hashlib.sha256(snapshot.encode("utf-8")).hexdigest() == provenance["config_sha256"]


def test_dataset_provenance_paths_are_repo_relative() -> None:
    report = _report()
    assert report["datasets"]
    for dataset in report["datasets"]:
        assert dataset["path"] == SUPPORT_DATA
        assert not Path(dataset["path"]).is_absolute()


def test_validate_result_accepts_a_faithful_committed_report(tmp_path: Path) -> None:
    report = _report()
    stem = _write_bundle(tmp_path, report)
    assert validate_result(report, path=tmp_path / f"{stem}.json") == []


def test_validate_result_flags_tampered_snapshot_and_dataset(tmp_path: Path) -> None:
    report = _report()
    stem = _write_bundle(tmp_path, report)
    path = tmp_path / f"{stem}.json"

    report["provenance"]["config_snapshot"] = report["provenance"]["config_snapshot"] + "\n# drift"
    problems = validate_result(report, path=path)
    assert any("config_snapshot" in problem for problem in problems)

    report = _report()
    report["datasets"][0]["sha256"] = "0" * 64
    problems = validate_result(report, path=path)
    assert any("dataset hash mismatch" in problem for problem in problems)


def test_validate_result_requires_canonical_filename_and_timestamp(tmp_path: Path) -> None:
    report = _report()
    bad_name = tmp_path / "report.json"
    problems = validate_result(report, path=bad_name)
    assert any("filename" in problem for problem in problems)

    wrong_day = tmp_path / f"1999-01-01-{report['provenance']['git_sha'][:7]}.json"
    problems = validate_result(report, path=wrong_day)
    assert any("filename date" in problem for problem in problems)


def test_discover_results_collects_siblings_and_flags_orphans(tmp_path: Path) -> None:
    report = _report()
    stem = _write_bundle(tmp_path, report)
    (tmp_path / "stray.md").write_text("orphan", encoding="utf-8")

    discovered = discover_results(tmp_path)
    assert [entry.stem for entry in discovered["entries"]] == [stem]
    entry = discovered["entries"][0]
    assert entry.md_path is not None and entry.csv_path is not None
    assert {path.name for path in entry.svg_paths} == {
        f"{stem}-pareto.svg",
        f"{stem}-latency.svg",
    }
    assert [Path(item).name for item in discovered["orphans"]] == ["stray.md"]
    assert any("orphaned artifact" in problem for problem in index_problems(discovered))


def test_results_index_links_every_artifact(tmp_path: Path) -> None:
    report = _report()
    stem = _write_bundle(tmp_path, report)
    discovered = discover_results(tmp_path)
    index = render_results_index(discovered)

    assert "Generated by `python -m app.benchmark_results`" in index
    assert f"`{stem}`" in index
    assert "reference CPU profile" in index
    recommended = report["recommended"]["combination_id"]
    assert f"| {recommended} |" in index
    links = re.findall(r"\]\(results/([^)]+)\)", index)
    assert {f"{stem}.json", f"{stem}.md", f"{stem}.csv"} <= set(links)
    assert f"{stem}-pareto.svg" in links
    for link in links:
        assert (tmp_path / link).exists()


def test_benchmark_results_cli_writes_and_checks_the_index(tmp_path: Path) -> None:
    report = _report()
    stem = _write_bundle(tmp_path, report)
    results_dir = tmp_path
    index_path = tmp_path / "README.md"

    assert benchmark_results_cli.main(
        ["--results-dir", str(results_dir), "--out", str(index_path)]
    ) == 0
    content = index_path.read_text(encoding="utf-8")
    assert stem in content
    assert benchmark_results_cli.main(
        ["--results-dir", str(results_dir), "--out", str(index_path), "--check"]
    ) == 0

    payload = json.loads((tmp_path / f"{stem}.json").read_text(encoding="utf-8"))
    payload["provenance"]["config_snapshot"] += "\n# tampered"
    (tmp_path / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")
    assert benchmark_results_cli.main(
        ["--results-dir", str(results_dir), "--out", str(index_path), "--check"]
    ) == 1


def test_plots_are_rendered_from_the_report_only() -> None:
    report = _report()
    pareto = render_pareto_svg(report)
    latency = render_latency_svg(report)

    assert pareto.startswith("<svg")
    assert latency.startswith("<svg")
    for row in report["rows"]:
        combo = str(row["combination_id"])
        assert combo in pareto
        assert combo in latency
    assert f"frontier: {len(report['pareto_frontier'])} of {report['num_combinations']}" in pareto
    assert "Latency (ms)" in latency
    assert "reference CPU numbers" in pareto


def test_write_plots_emits_both_files(tmp_path: Path) -> None:
    report = _report()
    paths = write_plots(report, tmp_path, stem="2026-01-01-deadbee")
    assert [path.name for path in paths] == [
        "2026-01-01-deadbee-pareto.svg",
        "2026-01-01-deadbee-latency.svg",
    ]
    assert all(path.exists() and path.read_text(encoding="utf-8").startswith("<svg") for path in paths)


def test_reference_suite_is_bounded_and_covers_all_corpora() -> None:
    config = load_benchmarks_config()
    suite = resolve_suite(config, "reference")

    assert suite["datasets"] == ["enterprise-it", "product-docs", "support"]
    assert int(suite["max_cases"]) == 6
    assert int(suite["max_combinations"]) == 4
    combinations = expand_combinations(normalize_parameters(suite["parameters"]), 4)
    assert len(combinations) == 4


def test_empty_results_directory_renders_an_honest_index(tmp_path: Path) -> None:
    discovered = discover_results(tmp_path)
    index = render_results_index(discovered)
    assert "No benchmark results are committed yet." in index
    assert index_problems(discovered) == []


def test_validate_result_requires_provenance_fields() -> None:
    report = _report()
    report["provenance"].pop("timestamp")
    problems = validate_result(report)
    assert any("provenance.timestamp" in problem for problem in problems)
